#!/usr/bin/env python3
"""call_radar.py · 调用选品雷达判断接口,读 payload 组装请求,把成品报告落盘。

工作流:读 payload.json → 调用判断接口 → 输出成品报告 markdown。

A-lite(2026-08-06)两步交互(根治 Codex/agent 同步超时丢报告/误判失败):
  提交 submit(默认):POST /full_judge,30s 内出结果→落盘;30s 没好→主动优雅退出,
    打印 poll 命令(exit 0,不报错、不扣额外额度)。服务端不知情继续跑完写库。
  轮询 poll:python3 scripts/call_radar.py poll <报告编号> → GET /task/{id},
    done→落盘 / running→提示等待 / error→报错。
  每次 agent 命令都 <30s,绕开 Codex/Cursor 命令超时(报告不再靠运气落盘)。

payload.json 结构(由本脚本与用户交互组装):
  target: {categoryName, nodeId, site}  品类名+nodeId(resolve_category 确认拿到)+ 站点;给 ASIN 时 {asin, site}(后台反推类目)
  profile: {experience, category_relation, capital}
  budget_cny: 选品预算(元)
  user_overrides: {} 或 {cvr,return_rate,purchase,...}  选填实测(没有就空,系统估算)

利润参数由系统基于市场数据估算,本脚本不传利润相关字段。
选品阶段用户拿不出出厂价,所以不填利润档。

用法:
  python3 scripts/call_radar.py payload.json        # 提交(30s 没好会提示 poll)
  python3 scripts/call_radar.py poll <报告编号>       # 轮询拿报告

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
import random
import urllib.request
import urllib.error
from urllib.parse import quote
import base64
import re

FULL_JUDGE_PATH = '/v1/天眼/full_judge'
DEFAULT_BASE = 'http://127.0.0.1:8000'
TIMEOUT = 30  # A-lite:故意短,让本脚本在 Codex 命令超时(~60-120s)前主动优雅退出转 poll(不报错)

# 复现服务端 gen_trace_id 格式(radar-+6位),让 deadline 断开后客户端知道 trace_id 能 poll
_TRACE_ALPHABET = '23456789abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ'  # 与服务端一致(无0/O/1/I/L)


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


def _gen_trace_id():
    """A-lite:复现服务端 gen_trace_id(radar-+6位),deadline 断开后凭它 poll。trace_id 非 secret,用 random 即可。"""
    return 'radar-' + ''.join(random.choice(_TRACE_ALPHABET) for _ in range(6))


def _deliver(result, payload, trace_id):
    """落盘报告+数据表(submit 成功 / poll done 共用)。无 report_markdown 时打印 JSON。
    不含 _save_profile(submit 在外单独调;poll 不调)。"""
    md = result.get('report_markdown', '')
    if not md:
        print(json.dumps(result, ensure_ascii=False))
        return
    reports_root = os.path.join(_skill_root(), 'reports')
    meta = result.get('_meta') or {}
    tid = trace_id or result.get('trace_id') or meta.get('trace_id') or 'no-id'
    cat = (payload.get('target') or {}).get('categoryName', '')
    site = (payload.get('target') or {}).get('site', '')
    safe_cat = re.sub(r'[\\/:*?"<>|\s]', '', str(cat))[:20] or '选品'
    sub_dir = os.path.join(reports_root, f"{safe_cat}{site}站-{tid}")
    os.makedirs(sub_dir, exist_ok=True)
    with open(os.path.join(sub_dir, '选品报告.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    print(md)
    xlsx_note = ''
    xlsx_b64 = result.get('report_xlsx_b64')
    if xlsx_b64:
        try:
            with open(os.path.join(sub_dir, '选品数据.xlsx'), 'wb') as f:
                f.write(base64.b64decode(xlsx_b64))
            xlsx_note = ' + 选品数据.xlsx'
        except Exception as e:
            print(f'⚠️ 源数据表格保存失败: {e}', file=sys.stderr)
    est = '利润由选品雷达估算' if (meta.get('estimated_profit') or result.get('estimated_profit')) else '利润由用户提供'
    print(f'✅ [天眼 v3.4] 已存到 {sub_dir}/ (选品报告.md{xlsx_note}) | 本次 ID: {tid} | 倾向 {result.get("tendency")} | 可信度 {result.get("confidence")} | {est}', file=sys.stderr)


def _prompt_poll(trace_id, why):
    """A-lite:deadline 到 / 服务端 running → 主动优雅退出 + poll 提示(exit 0,不报错)。"""
    print(f'⏳ [天眼 v3.4] {why}', file=sys.stderr)
    print('   分析仍在进行(单次需 3-6 分钟,数据量大)。约 2-4 分钟后运行下面命令拿报告(不扣额度,查的是同一个任务):', file=sys.stderr)
    print(f'   python3 scripts/call_radar.py poll {trace_id}', file=sys.stderr)
    sys.exit(0)


def _poll(trace_id):
    """A-lite poll 子命令:GET /task/{trace_id}。done→落盘 / running→提示等待 / error→报错。"""
    _base = _get_endpoint().rsplit('/full_judge', 1)[0].rstrip('/')   # 去掉 /full_judge → /v1/天眼 基
    url = quote(_base + '/task/' + trace_id, safe=':/?=&%+@')
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {API_KEY}')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            pass
        if e.code == 404:
            print(f'❌ [天眼 v3.4] 查不到任务 {trace_id}(编号错或已过期超 90 天)。确认编号后重试,或联系客服 buluslan(公众号:新西楼.AI)', file=sys.stderr)
        else:
            print(f'❌ [天眼 v3.4] 查询失败(HTTP {e.code}): {detail}', file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f'❌ [天眼 v3.4] 查询连接失败: {e.reason}', file=sys.stderr)
        sys.exit(1)
    status = result.get('status')
    if status == 'done':
        _deliver(result, {}, trace_id)   # poll 拿不到 payload,文件夹名用 trace_id 兜底(含 tid 可搜)
        sys.exit(0)
    if status == 'running':
        print('⏳ [天眼 v3.4] 任务仍在跑,请再等 1-2 分钟后重新运行:', file=sys.stderr)
        print(f'   python3 scripts/call_radar.py poll {trace_id}', file=sys.stderr)
        sys.exit(0)
    print(f'❌ [天眼 v3.4] 任务状态异常({status})。联系客服 buluslan(公众号:新西楼.AI)凭编号 {trace_id} 处理', file=sys.stderr)
    sys.exit(1)


def main():
    # A-lite:poll 子命令分流
    if len(sys.argv) >= 2 and sys.argv[1] == 'poll':
        if len(sys.argv) < 3:
            print('[天眼 v3.4] 用法: python3 scripts/call_radar.py poll <报告编号>', file=sys.stderr)
            sys.exit(1)
        _poll(sys.argv[2])
        return

    if len(sys.argv) < 2:
        print('[天眼 v3.4] 用法:\n  提交: python3 scripts/call_radar.py <payload.json>\n  轮询: python3 scripts/call_radar.py poll <报告编号>', file=sys.stderr)
        sys.exit(1)

    payload_path = sys.argv[1]
    if not os.path.exists(payload_path):
        print(f'❌ 输入文件不存在: {payload_path}', file=sys.stderr)
        sys.exit(1)

    with open(payload_path, encoding='utf-8') as f:
        payload = json.load(f)

    # 利润参数由系统基于市场数据估算,本脚本不传利润相关字段
    payload.setdefault('user_overrides', {})

    # 幂等键(配合服务端去重,防 agent 连环重试各扣一次额度):同品类同站点 5 分钟窗口内复用同一键
    import time as _time
    _tgt = payload.get('target') or {}
    _window = int(_time.time() // 300)  # 5 分钟窗口
    payload['idempotency_key'] = f"{_tgt.get('categoryName','')}_{_tgt.get('asin','')}_{_tgt.get('site','')}_{_window}"

    # A-lite:客户端生成 trace_id 提交,deadline 断开后凭它 poll(服务端收到 client_trace_id 则采用)
    trace_id = _gen_trace_id()
    payload['client_trace_id'] = trace_id

    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(ENDPOINT, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {API_KEY}')
    req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            remaining = resp.headers.get('X-RateLimit-Remaining', '')   # 读剩余额度(云端已写)
            result = json.loads(resp.read().decode('utf-8'))
            if remaining:
                print(f'ℹ️ [天眼 v3.4] 剩余额度: {remaining}', file=sys.stderr)
            # A-lite:服务端可能返回 running(幂等命中 running 态等)→ 转 poll 提示
            if result.get('status') == 'running':
                _prompt_poll(result.get('trace_id') or trace_id, '任务已提交,仍在跑')
            _deliver(result, payload, trace_id)
            _save_profile(payload)
            sys.exit(0)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            pass
        if e.code in (401, 403):
            print(f'❌ [天眼 v3.4] API key 失效或次数用完,联系客服 buluslan(公众号:新西楼.AI)(HTTP {e.code}): {detail}', file=sys.stderr)
        elif e.code in (500, 502, 503, 504):
            print(f'❌ [天眼 v3.4] 云端服务异常(HTTP {e.code}): {detail}', file=sys.stderr)
            print(f'   任务可能仍在跑,稍后可凭编号查: python3 scripts/call_radar.py poll {trace_id}', file=sys.stderr)
        else:
            print(f'❌ [天眼 v3.4] 判断失败 HTTP {e.code}: {detail}', file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        reason = str(e.reason)
        if 'timeout' in reason.lower() or 'timed out' in reason.lower():
            # A-lite:30s deadline 到 = 服务端还在跑(正常,单次需 3-6 分钟)→ 优雅退出转 poll,不报错
            _prompt_poll(trace_id, f'分析仍在进行(已等 {TIMEOUT}s)')
        else:
            print(f'❌ [天眼 v3.4] 连接选品雷达失败(请确认服务已启动、地址配置正确): {reason}', file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f'❌ [天眼 v3.4] 判断遇到未知问题({type(e).__name__}): {str(e)[:200]}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
