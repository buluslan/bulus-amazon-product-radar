#!/usr/bin/env python3
"""resolve_category.py · 品类名→候选类目列表(供用户确认 nodeId)

用法:用户给品类名后,shell(SKILL.md)调本脚本 → 返候选类目编号列表 →
     agent 念给用户选 → 拿 nodeId 写进 payload.target 再调 call_radar.py。

工作流:读 skill/.env → POST 云端 /v1/天眼/resolve_category → 解析 JSON → 打印候选编号列表。

🔑 不消耗 quota(只鉴权),不走 LLM。云端多变体合并(单复数)+配件降权,成品正主排 top1。
   模板仿 check_quota.py(2026-07-31 新增,配合类目转译 bug 修复·路线1·壳端确认 nodeId)。

不编造结果。失败返大白话报错。
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from urllib.parse import quote

RESOLVE_PATH = '/v1/天眼/resolve_category'
DEFAULT_BASE = 'http://127.0.0.1:8000'
TIMEOUT = 30


def _skill_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_env():
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
    env = _read_env()
    base = (os.environ.get('RADAR_ENDPOINT') or env.get('RADAR_ENDPOINT') or DEFAULT_BASE).rstrip('/')
    return quote(base + RESOLVE_PATH, safe=':/?=&%+')


def _get_api_key():
    env = _read_env()
    return os.environ.get('RADAR_API_KEY') or env.get('RADAR_API_KEY') or 'your-api-key'


def _read_shell_version():
    skill_md = os.path.join(_skill_root(), 'SKILL.md')
    try:
        with open(skill_md, encoding='utf-8') as f:
            text = f.read()
        m = re.search(r'^version:\s*"?([^"\n]+)"?', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return 'unknown'


def _format_candidates(data):
    """候选类目列表 → 编号 + leafLabel + nodeId + 商品数(供 agent 念给用户选)。"""
    cands = data.get('candidates') or []
    if not cands:
        return '未找到候选类目'
    lines = []
    for i, c in enumerate(cands, 1):
        label = c.get('leafLabel') or '?'
        nid = c.get('leafNodeId') or '?'
        prods = c.get('products') or 0
        lines.append(f"  {i}. {label}  (nodeId={nid}, {prods} 商品)")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='品类名→候选类目列表(供用户确认 nodeId)')
    parser.add_argument('category_name', help='品类名(如 robot vacuum / 扫地机器人)')
    parser.add_argument('--site', default='US', help='站点(默认 US)')
    parser.add_argument('--endpoint', help='临时覆盖云端地址')
    parser.add_argument('--api-key', help='临时覆盖 api key')
    parser.add_argument('--json', action='store_true', help='返原始 JSON,不格式化')
    args = parser.parse_args()

    api_key = args.api_key or _get_api_key()
    if api_key == 'your-api-key' or not api_key:
        print('❌ 没找到 API key。请先安装 skill(install.sh),或检查 .env 里的 RADAR_API_KEY。', file=sys.stderr)
        sys.exit(1)

    if args.endpoint:
        endpoint = quote(args.endpoint.rstrip('/') + RESOLVE_PATH, safe=':/?=&%+')
    else:
        endpoint = _get_endpoint()
    body = json.dumps({'categoryName': args.category_name, 'site': args.site}).encode('utf-8')
    req = urllib.request.Request(endpoint, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {api_key}')
    req.add_header('Content-Type', 'application/json')

    shell_ver = _read_shell_version()

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            print('❌ API key 无效或已失效,请联系管理员', file=sys.stderr)
        elif e.code == 400:
            detail = ''
            try:
                detail = json.loads(e.read().decode('utf-8')).get('detail', '')
            except Exception:
                pass
            print(f'❌ {detail or "未搜到该品类,换个说法重试(换复数/同义词)"}', file=sys.stderr)
        else:
            print(f'❌ 品类搜索失败 HTTP {e.code}', file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f'❌ 连接云端失败(确认服务可访问): {e.reason}', file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if not data.get('ok'):
        print(f'❌ 云端返错: {data.get("error", data)}', file=sys.stderr)
        sys.exit(1)

    print(f'✅ [天眼 {shell_ver}] 「{args.category_name}」候选类目(按相关度排,成品优先):\n')
    print(_format_candidates(data))
    print('\n👉 请用户选一个(说编号或名字),拿到 nodeId 后写进 payload.target')


if __name__ == '__main__':
    main()
