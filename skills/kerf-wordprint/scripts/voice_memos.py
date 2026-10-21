#!/usr/bin/env python3
"""List Apple Voice Memos newest first as JSON: title, recorded_at (ISO), duration (s), path.

Reads a temporary copy of the database so the Voice Memos app is never locked or modified.
"""
import datetime
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

RECORDINGS = Path.home() / 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
APPLE_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
QUERY = ('SELECT ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH FROM ZCLOUDRECORDING '
         'WHERE ZEVICTIONDATE IS NULL ORDER BY ZDATE DESC')
# Unnamed memos store their creation time as the label, e.g. 2026-10-15T06:01:31Z.
ISO_LABEL = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?')


def title(label, recorded, stem):
    if label and recorded and ISO_LABEL.fullmatch(label.strip()):
        return f'語音備忘錄 {recorded:%m-%d %H:%M}'
    return label or stem


def memos(recordings=RECORDINGS):
    with tempfile.TemporaryDirectory() as temp:
        for suffix in ('', '-wal', '-shm'):
            source = recordings / f'CloudRecordings.db{suffix}'
            if source.exists() or not suffix:
                shutil.copy2(source, Path(temp) / source.name)
        connection = sqlite3.connect(Path(temp) / 'CloudRecordings.db')
        try:
            rows = connection.execute(QUERY).fetchall()
        finally:
            connection.close()
    result = []
    for label, date, duration, path in rows:
        if not path:
            continue
        audio = Path(path) if Path(path).is_absolute() else recordings / path
        recorded = (APPLE_EPOCH + datetime.timedelta(seconds=date)).astimezone() if date is not None else None
        result.append({'title': title(label, recorded, audio.stem), 'recorded_at': recorded.isoformat(timespec='seconds') if recorded else None,
                       'duration': round(duration or 0, 1), 'path': str(audio)})
    return result


def main():
    try:
        print(json.dumps(memos(), ensure_ascii=False, indent=2))
        return 0
    except FileNotFoundError:  # Voice Memos never used on this Mac.
        print('[]')
        return 0
    except PermissionError:
        print('需要完整磁碟取用權，或把備忘錄拖到資料夾', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
