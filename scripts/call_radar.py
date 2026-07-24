#!/usr/bin/env python3
"""call_radar.py · 调用选品雷达判断接口,读 payload 组装请求,把成品报告落盘。

工作流:读 payload.json → 调用判断接口 → 输出成品报告 markdown。

payload.json 结构(由本脚本与用户交互组装):
  target: {categoryName, site}         品类名 + 站点
  profile: {experience, category_relation, capital}
  budget_cny: 选品预算(元)
  user_overrides: {} 或 {cvr,return_rate,purchase,...}  选填实测(没有就空,系统估算)

利润参数由系统基于市场数据估算,本脚本不传利润相关字段。
选品阶段用户拿不出出厂价,所以不填利润档。

用法:
  python3 scripts/call_radar.py payload.json

配置(优先级从高到低,任一档有值即用):
  环境变量 RADAR_ENDPOINT / RADAR_API_KEY   临时覆盖
  skill 文件夹/.env 里的连接地址和 key       install.sh 写入(默认)
  内置默认

成功时输出报告 markdown;状态/错误信息输出到标准错误流。
失败时退出码 1 并提示,选品雷达失败时不编造结果。
"""
import json
import os
import sys
import urllib.request
import urllib.error
from urllib.parse import quote
import base64
import re

FULL_JUDGE_PATH = '/v1/天眼/full_judge'
DEFAULT_BASE = 'http://127.0.0.1:8000'
TIMEOUT = 480  # 判断耗时较长,留足余量


def _skill_root():
    """skill 根目录(scripts 的父)。.env / reports 都在这,不散到 ~/.radar 全局目录。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_env():
    """读 skill 根/.env(RADAR_ENDPOINT / RADAR_API_KEY)。失败返回 {}。纯标准库 parse(不引 dotenv)。"""
    path = os.path.join(_skill_root(), '.env')
    env = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env


def _get_endpoint():
    """连接地址 = 环境变量 > skill/.env > 默认;自动补全判断接口路径。"""
    env = _read_env()
    base = (os.environ.get('RADAR_ENDPOINT') or env.get('RADAR_ENDPOINT') or DEFAULT_BASE).rstrip('/')
    return base if '/full_judge' in base else base + FULL_JUDGE_PATH


def _get_api_key():
    """api key = 环境变量 > skill/.env > 默认。"""
    env = _read_env()
    return os.environ.get('RADAR_API_KEY') or env.get('RADAR_API_KEY') or 'your-api-key'


ENDPOINT = quote(_get_endpoint(), safe=':/?=&%+@')  # 编码中文路径,保留 URL 结构符
API_KEY = _get_api_key()


def main():
    if len(sys.argv) < 2:
        print('[天眼 v3.3] 用法: python3 scripts/call_radar.py <payload.json>', file=sys.stderr)
        print('payload.json = {target:{categoryName,site}, profile, budget_cny, user_overrides?}', file=sys.stderr)
        sys.exit(1)

    payload_path = sys.argv[1]
    if not os.path.exists(payload_path):
        print(f'❌ 输入文件不存在: {payload_path}', file=sys.stderr)
        sys.exit(1)

    with open(payload_path, encoding='utf-8') as f:
        payload = json.load(f)

    # 利润参数由系统基于市场数据估算,本脚本不传利润相关字段
    # 调研参数由接口默认,无需用户指定
    payload.setdefault('user_overrides', {})

    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {API_KEY}')
    req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            remaining = resp.headers.get('X-RateLimit-Remaining', '')   # 读剩余额度(云端已写)
            result = json.loads(resp.read().decode('utf-8'))
            if remaining:
                print(f'ℹ️ [天眼 v3.3] 剩余额度: {remaining}', file=sys.stderr)
            md = result.get('report_markdown', '')
            if not md:
                # 无 report_markdown 时输出 JSON(兼容场景)
                print(json.dumps(result, ensure_ascii=False))
            else:
                # 系统返回成品 markdown + 源数据 xlsx,本脚本同时落盘,文件名都带 trace_id
                # 存到 skill 文件夹/reports/(用户好找;不随工作目录漂,换设备/重装一致)
                out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'reports')
                os.makedirs(out_dir, exist_ok=True)
                meta = result.get('_meta', {})
                trace_id = result.get('trace_id') or meta.get('trace_id') or 'no-id'
                cat = (payload.get('target') or {}).get('categoryName', '选品')
                site = (payload.get('target') or {}).get('site', '')
                safe_cat = re.sub(r'[\\/:*?"<>|\s]', '', str(cat))[:20] or '选品'
                base_name = f"选品分析报告-{safe_cat}{site}站-{trace_id}"
                md_path = os.path.join(out_dir, base_name + '.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md)
                print(md)  # 打印报告 markdown
                xlsx_note = ''
                xlsx_b64 = result.get('report_xlsx_b64')
                if xlsx_b64:
                    try:
                        xlsx_path = os.path.join(out_dir, f"选品分析数据-{safe_cat}{site}站-{trace_id}.xlsx")
                        with open(xlsx_path, 'wb') as f:
                            f.write(base64.b64decode(xlsx_b64))
                        xlsx_note = f" + {os.path.basename(xlsx_path)}"
                    except Exception as e:
                        print(f'⚠️ 源数据表格保存失败: {e}', file=sys.stderr)
                est = '利润由选品雷达估算' if meta.get('estimated_profit') else '利润由用户提供'
                print(f'✅ [天眼 v3.3] 已存 {md_path}{xlsx_note} | 本次 ID: {trace_id} | 倾向 {result.get("tendency")} | 可信度 {result.get("confidence")} | {est}', file=sys.stderr)
            sys.exit(0)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            pass
        if e.code in (401, 403):
            print(f'❌ [天眼 v3.3] API key 失效或次数用完,联系客服(HTTP {e.code}): {detail}', file=sys.stderr)
        elif e.code in (500, 502, 503, 504):
            print(f'❌ [天眼 v3.3] 云端服务异常,稍后重试(HTTP {e.code}): {detail}', file=sys.stderr)
        else:
            print(f'❌ [天眼 v3.3] 判断失败 HTTP {e.code}: {detail}', file=sys.stderr)
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if 'timeout' in reason.lower() or 'timed out' in reason.lower():
            print(f'❌ [天眼 v3.3] 判断超时(数据量大),建议稍后重试: {reason}', file=sys.stderr)
        else:
            print(f'❌ [天眼 v3.3] 连接选品雷达失败(请确认服务已启动、地址配置正确): {reason}', file=sys.stderr)
    except Exception as e:
        print(f'❌ [天眼 v3.3] 判断遇到未知问题({type(e).__name__}): {str(e)[:200]}', file=sys.stderr)

    print('→ 选品雷达暂时无法响应,请稍后重试', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
