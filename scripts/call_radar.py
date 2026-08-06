#!/usr/bin/env python3
"""call_radar.py · 调用选品雷达判断接口,读 payload 组装请求,把成品报告落盘。

工作流:读 payload.json → 调用判断接口 → 输出成品报告 markdown。

payload.json 结构(由本脚本与用户交互组装):
  target: {categoryName, nodeId, site}  品类名+nodeId(resolve_category 确认拿到)+ 站点;给 ASIN 时 {asin, site}(后台反推类目)
  profile: {experience, category_relation, capital}
  budget_cny: 选品预算(元)
  user_overrides: {} 或 {cvr,return_rate,purchase,...}  选填实测(没有就空,系统估算)

利润参数由系统基于市场数据估算,本脚本不传利润相关字段。
选品阶段用户拿不出出厂价,所以不填利润档。

用法:
  python3 scripts/call_radar.py payload.json

配置(优先级从高到低,任一档有值即用):
  环境变量 RADAR_ENDPOINT / RADAR_API_KEY   临时覆盖
  skill 文件夹/.env 里的连接地址和 key       cp .env.example 写入(默认)
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


def _save_profile(payload):
    """提交后把卖家画像落盘到 .flow_state/seller_profile.json(下次调用先读它,治"每次重填画像")。
    只存 profile + budget_cny + user_overrides(品类 target 每次不同,不缓存)。fail-soft,不影响主流程。"""
    try:
        from datetime import datetime
        p = payload.get('profile') or {}
        prof = {
            'experience': p.get('experience', ''),
            'category_relation': p.get('category_relation', ''),
            'capital': p.get('capital', ''),
            'budget_cny': payload.get('budget_cny', 0),
            'supply_chain': p.get('supply_chain', ''),
            'business_model': p.get('business_model', ''),
            'user_overrides': payload.get('user_overrides', {}),
            'ts': datetime.now().isoformat(timespec='seconds'),
        }
        flow_dir = os.path.join(_skill_root(), '.flow_state')
        os.makedirs(flow_dir, exist_ok=True)
        with open(os.path.join(flow_dir, 'seller_profile.json'), 'w', encoding='utf-8') as f:
            json.dump(prof, f, ensure_ascii=False, indent=2)
    except Exception:
        pass   # 画像缓存是锦上添花,失败不阻塞报告交付


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

    # 幂等键(配合服务端去重,防 agent 连环重试各扣一次额度):同品类同站点 5 分钟窗口内复用同一键
    import time as _time
    _tgt = payload.get('target') or {}
    _window = int(_time.time() // 300)  # 5 分钟窗口
    payload['idempotency_key'] = f"{_tgt.get('categoryName','')}_{_tgt.get('asin','')}_{_tgt.get('site','')}_{_window}"

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
                # 按 trace 建子文件夹:报告+数据同文件夹下发,文件名统一(治"md/xlsx 平铺且前缀不一难找")
                reports_root = os.path.join(_skill_root(), 'reports')
                meta = result.get('_meta', {})
                trace_id = result.get('trace_id') or meta.get('trace_id') or 'no-id'
                cat = (payload.get('target') or {}).get('categoryName', '选品')
                site = (payload.get('target') or {}).get('site', '')
                safe_cat = re.sub(r'[\\/:*?"<>|\s]', '', str(cat))[:20] or '选品'
                sub_dir = os.path.join(reports_root, f"{safe_cat}{site}站-{trace_id}")
                os.makedirs(sub_dir, exist_ok=True)
                md_path = os.path.join(sub_dir, '选品报告.md')
                with open(md_path, 'w', encoding='utf-8') as f:
                    f.write(md)
                print(md)  # 打印报告 markdown
                xlsx_note = ''
                xlsx_b64 = result.get('report_xlsx_b64')
                if xlsx_b64:
                    try:
                        xlsx_path = os.path.join(sub_dir, '选品数据.xlsx')
                        with open(xlsx_path, 'wb') as f:
                            f.write(base64.b64decode(xlsx_b64))
                        xlsx_note = ' + 选品数据.xlsx'
                    except Exception as e:
                        print(f'⚠️ 源数据表格保存失败: {e}', file=sys.stderr)
                _save_profile(payload)   # 画像落盘(下次免重填)
                est = '利润由选品雷达估算' if meta.get('estimated_profit') else '利润由用户提供'
                print(f'✅ [天眼 v3.3] 已存到 {sub_dir}/ (选品报告.md{xlsx_note}) | 本次 ID: {trace_id} | 倾向 {result.get("tendency")} | 可信度 {result.get("confidence")} | {est}', file=sys.stderr)
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
            print(f'❌ [天眼 v3.3] 判断超时(数据量大,单次需3-6分钟)。请勿立即重试(会重复扣额度),如需重试请确认后手动提交: {reason}', file=sys.stderr)
        else:
            print(f'❌ [天眼 v3.3] 连接选品雷达失败(请确认服务已启动、地址配置正确): {reason}', file=sys.stderr)
    except Exception as e:
        print(f'❌ [天眼 v3.3] 判断遇到未知问题({type(e).__name__}): {str(e)[:200]}', file=sys.stderr)

    print('→ 选品雷达暂时无法响应。请勿立即重试(避免重复扣额度),联系客服 buluslan 凭报告编号处理,或确认后手动重试', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
