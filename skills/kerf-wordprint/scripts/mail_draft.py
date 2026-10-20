#!/usr/bin/env python3
"""Open a Mail.app draft with the transcript attached. It only shows the draft; it never sends."""
import argparse
import subprocess
import sys
from pathlib import Path


def quote(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('\r', '').replace('\n', '\\n') + '"'


def script(recipients, title, summary, attachments):
    body = (summary.strip() + '\n\n' if summary.strip() else '') + '附件：\n' + ''.join(f'- {p.name}\n' for p in attachments)
    lines = ['tell application "Mail"',
             f'  set draft to make new outgoing message with properties {{subject:{quote("逐字稿：" + title)}, '
             f'content:{quote(body)}, visible:true}}',
             '  tell draft']
    lines += [f'    make new to recipient at end of to recipients with properties {{address:{quote(r)}}}' for r in recipients]
    lines += [f'    make new attachment with properties {{file name:(POSIX file {quote(str(p))})}} at after the last paragraph'
              for p in attachments]
    lines += ['  end tell', '  activate', 'end tell']  # No `send`: the user reviews and sends it themselves.
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title', required=True, help='recording name; subject becomes 逐字稿：<title>')
    parser.add_argument('--summary', default='', help='one-sentence conclusion for the body')
    parser.add_argument('--to', action='append', default=[], help='recipient address; repeatable, may be omitted')
    parser.add_argument('--attach', action='append', default=[], type=Path, help='file to attach; repeatable')
    parser.add_argument('--dry-run', action='store_true', help='print the AppleScript without running it')
    args = parser.parse_args()
    attachments = [p.resolve() for p in args.attach]
    missing = [str(p) for p in attachments if not p.is_file()]
    if missing:
        print('找不到附件：' + '、'.join(missing), file=sys.stderr)
        return 1
    text = script(args.to, args.title, args.summary, attachments)
    if args.dry_run:
        print(text, end='')
        return 0
    try:
        result = subprocess.run(['osascript', '-'], input=text, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        print('Mail 沒有回應（可能在等自動化權限對話框）；草稿未確認建立。', file=sys.stderr)
        return 1
    if result.returncode:
        print(f'Mail 草稿失敗：{result.stderr.strip()}', file=sys.stderr)
        return 1
    print('已開啟 Mail 草稿，尚未寄出。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
