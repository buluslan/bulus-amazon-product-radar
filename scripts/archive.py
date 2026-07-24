#!/usr/bin/env python3
"""archive.py · 一键归档本次分析(把本地对话打包上传云端,关联 trace_id)

工作流:读 trace_id + 对话 md → 打包 zip(对话 + meta) → POST 云端归档接口。

🔑 只打包对话:报告 / 数据 / 运行日志云端已存有,
   客服凭报告编号自取。归档只补"云端没有的"——用户本地对话。

用法:
  python3 scripts/archive.py <trace_id> --conversation <对话md路径>

配置(优先级,同 call_radar.py):
  环境变量 RADAR_ENDPOINT / RADAR_API_KEY            临时覆盖
  ~/.radar/config.json 里的连接地址和 key            部署时写入(默认)
  内置默认

成功打印归档编号;失败退出码 1。不编造结果。
"""
import argparse
import base64
import io
import json
import os
import re
import socket
import sys
import urllib.request
import urllib.error
from datetime import datetime
from urllib.parse import quote
from zipfile import ZipFile

ARCHIVE_PATH = '/v1/天眼/archive'
DEFAULT_BASE = 'http://127.0.0.1:8000'
TIMEOUT = 60  # 归档包小,60s 足够(远小于 full_judge 的 480s)


def _read_config():
    """读 ~/.radar/config.json(部署时写入的连接地址和 key)。失败返回 {}。"""
    path = os.path.expanduser('~/.radar/config.json')
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _get_endpoint():
    """连接地址 = 环境变量 > 配置文件 > 默认;自动补全归档接口路径。"""
    cfg = _read_config()
    base = (os.environ.get('RADAR_ENDPOINT') or cfg.get('cloud_endpoint') or DEFAULT_BASE).rstrip('/')
    return base if '/archive' in base else base + ARCHIVE_PATH


def _get_api_key():
    """api key = 环境变量 > 配置文件 > 默认。"""
    cfg = _read_config()
    return os.environ.get('RADAR_API_KEY') or cfg.get('api_key') or 'your-api-key'


def _read_shell_version():
    """读同壳 SKILL.md frontmatter 的 version(归档 meta 用,随壳版本自动)。失败返 'unknown'。"""
    skill_md = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'SKILL.md')
    try:
        with open(skill_md, encoding='utf-8') as f:
            text = f.read()
        m = re.search(r'^version:\s*"?([^"\n]+)"?', text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return 'unknown'


def _build_pack(trace_id, conversation_path):
    """打包 zip = conversation.md + meta.json。返回 (base64, 字节数)。"""
    with open(conversation_path, encoding='utf-8') as f:
        conversation_md = f.read()
    meta = {
        'trace_id': trace_id,
        'hostname': socket.gethostname(),
        'shell_version': _read_shell_version(),
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }
    buf = io.BytesIO()
    with ZipFile(buf, 'w') as zf:
        zf.writestr('conversation.md', conversation_md)
        zf.writestr('meta.json', json.dumps(meta, ensure_ascii=False, indent=2))
    return base64.b64encode(buf.getvalue()).decode('ascii'), len(buf.getvalue())


def main():
    parser = argparse.ArgumentParser(description='一键归档本次分析(打包对话上传云端)')
    parser.add_argument('trace_id', help='本次报告编号 radar-XXXXXX')
    parser.add_argument('--conversation', required=True, help='agent 整理的对话 md 路径')
    parser.add_argument('--endpoint', help='临时覆盖云端地址(默认读 config)')
    parser.add_argument('--api-key', help='临时覆盖 api key(默认读 config)')
    args = parser.parse_args()

    if not os.path.exists(args.conversation):
        print(f'❌ [天眼] 对话文件不存在: {args.conversation}', file=sys.stderr)
        sys.exit(1)

    trace_id = args.trace_id.strip()
    if not trace_id.startswith('radar-'):
        print(f'⚠️ [天眼] 报告编号看起来不对(应以 radar- 开头): {trace_id}', file=sys.stderr)

    shell_ver = _read_shell_version()
    pack_b64, pack_size = _build_pack(trace_id, args.conversation)

    endpoint = quote(args.endpoint or _get_endpoint(), safe=':/?=&%+@')
    api_key = args.api_key or _get_api_key()

    body = json.dumps({'trace_id': trace_id, 'pack_b64': pack_b64}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(endpoint, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {api_key}')
    req.add_header('Content-Type', 'application/json')

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            result = json.loads(resp.read().decode('utf-8'))   # 云端返回(含内部字段,不回显终端)
        print(f'✅ [天眼 {shell_ver}] 已打包上传,报告编号 {trace_id} | 对话 {pack_size / 1024:.1f}KB | 客服可凭此编号调取完整记录(对话 + 报告 + 运行日志)', file=sys.stderr)
        sys.exit(0)
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            pass
        if e.code in (401, 403):
            print(f'❌ [天眼] 归档失败,鉴权不通过或本次记录不属于你(HTTP {e.code}): {detail}', file=sys.stderr)
        elif e.code == 404:
            print(f'❌ [天眼] 云端没找到本次记录({trace_id}),确认编号没错(HTTP 404): {detail}', file=sys.stderr)
        else:
            print(f'❌ [天眼] 归档失败 HTTP {e.code}: {detail}', file=sys.stderr)
    except urllib.error.URLError as e:
        print(f'❌ [天眼] 连接云端失败(确认服务已启动、地址配置正确): {e.reason}', file=sys.stderr)
    except Exception as e:
        print(f'❌ [天眼] 归档遇到未知问题,请稍后重试或联系客服', file=sys.stderr)

    print('→ 归档未完成,可稍后重试', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    main()
