#!/usr/bin/env python3
"""List Voice Memos metadata using a private, validated WAL snapshot.

Never connect SQLite to the source, touch its SHM, or open audio while listing.
Only WAL-mode stores are supported; rollback journals need locking to copy safely.
"""
import datetime
import errno
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

RECORDINGS = Path.home() / 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings'
APPLE_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
QUERY = ('SELECT {display_title}, ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH FROM ZCLOUDRECORDING '
         'WHERE ZEVICTIONDATE IS NULL ORDER BY ZDATE DESC')
# Unnamed memos store their creation time as the label, e.g. 2026-10-15T06:01:31Z.
ISO_LABEL = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?')


def title(label, recorded, stem):
    if label and recorded and ISO_LABEL.fullmatch(label.strip()):
        return f'語音備忘錄 {recorded:%m-%d %H:%M}'
    return label or stem


class SnapshotError(ValueError):
    """The source cannot safely provide a consistent private snapshot."""


class _SourceChanged(Exception):
    pass


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode)


def _plain_stat(directory_fd, name):
    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode):
        raise SnapshotError('錄音清單或 WAL 不是一般檔案（不接受符號連結）')
    return _signature(info)


def _open_source(directory_fd, name):
    # NOFOLLOW closes the lstat/open race; NONBLOCK prevents a swapped-in FIFO
    # from hanging before fstat can reject it. No source descriptor is writable.
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory_fd)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SnapshotError('錄音清單或 WAL 不接受符號連結或非一般檔案') from error
        raise
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise SnapshotError('錄音清單或 WAL 不是一般檔案')
    return fd


def _file_state(directory_fd, name, header_size, optional=False):
    try:
        before = _plain_stat(directory_fd, name)
    except FileNotFoundError:
        if optional:
            return None
        raise
    with os.fdopen(_open_source(directory_fd, name), 'rb') as source:
        if _signature(os.fstat(source.fileno())) != before:
            raise _SourceChanged
        header = source.read(header_size)
        if (_signature(os.fstat(source.fileno())) != before
                or _plain_stat(directory_fd, name) != before):
            raise _SourceChanged
    return before, header


def _source_state(directory_fd):
    return (_file_state(directory_fd, 'CloudRecordings.db', 100),
            _file_state(directory_fd, 'CloudRecordings.db-wal', 32, optional=True))


def _copy_file(directory_fd, name, destination, expected):
    with os.fdopen(_open_source(directory_fd, name), 'rb') as source:
        if _signature(os.fstat(source.fileno())) != expected[0]:
            raise _SourceChanged
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as output:
            shutil.copyfileobj(source, output)
        if (_signature(os.fstat(source.fileno())) != expected[0]
                or _plain_stat(directory_fd, name) != expected[0]
                or destination.stat().st_size != expected[0][2]):
            raise _SourceChanged


@contextmanager
def _snapshot(directory_fd):
    for attempt in range(5):
        if attempt:
            time.sleep(0.01 * attempt)
        with tempfile.TemporaryDirectory(prefix='wordprint-voicememos-') as temp:
            os.chmod(temp, 0o700)
            database = Path(temp) / 'CloudRecordings.db'
            before = None
            try:
                before = _source_state(directory_fd)
                header = before[0][1]
                if len(header) != 100 or header[:16] != b'SQLite format 3\x00':
                    raise SnapshotError('讀不懂語音備忘錄的 SQLite 清單')
                if header[18:20] != b'\x02\x02':
                    raise SnapshotError('錄音清單不是 WAL 模式，無法安全建立快照')
                if before[1] is not None and before[1][0][2]:
                    wal_header = before[1][1]
                    if (len(wal_header) != 32
                            or wal_header[:4] not in (b'7\x7f\x06\x82', b'7\x7f\x06\x83')):
                        raise SnapshotError('讀不懂語音備忘錄的 WAL 標頭')
                # WAL first: a checkpoint during either copy invalidates the
                # before/after pair. Never inspect, copy, or open source -shm.
                if before[1] is not None:
                    _copy_file(directory_fd, 'CloudRecordings.db-wal',
                               Path(temp) / 'CloudRecordings.db-wal', before[1])
                _copy_file(directory_fd, 'CloudRecordings.db', database, before[0])
                if _source_state(directory_fd) != before:
                    raise _SourceChanged
            except _SourceChanged:
                continue
            except FileNotFoundError:
                # A genuinely absent source is actionable. A WAL disappearing
                # while copying, or a moving DB on later attempts, is retried.
                if attempt == 0 and before is None:
                    _plain_stat(directory_fd, 'CloudRecordings.db')
                continue
            except PermissionError:
                raise
            except OSError as error:
                raise SnapshotError('無法讀取或建立語音備忘錄清單快照') from error
            yield database
            return
    raise SnapshotError('語音備忘錄正在寫入清單，請稍後重新整理（已嘗試 5 次）')


def _plain_audio_name(name):
    return (isinstance(name, str) and bool(name) and not name.startswith('.')
            and not any(char in name for char in ('/', '\\', '\x00'))
            and Path(name).suffix.lower() in ('.m4a', '.qta'))


def _availability(directory_fd, name):
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (stat.S_ISREG(info.st_mode) and info.st_mode & 0o444
                and os.access(name, os.R_OK, dir_fd=directory_fd, follow_symlinks=False)
                and _signature(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) == _signature(info)):
            return 'local', info.st_size
    except FileNotFoundError:
        return 'missing', None
    except OSError:
        pass
    return 'unreadable', None


def memos(recordings=RECORDINGS):
    """Return newest-first rows; invalid names are skipped, symlinks unreadable.

    id is SHA-256 of the absolute source path encoded with os.fsencode; it does
    not depend on a label, availability, file contents, or the temporary copy.
    Missing source DB raises FileNotFoundError; CLI alone translates it to [].
    """
    recordings = Path(os.path.abspath(os.fspath(recordings)))
    try:
        directory_fd = os.open(recordings, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise SnapshotError('錄音資料夾不是一般資料夾（不接受符號連結）') from error
        raise
    try:
        with _snapshot(directory_fd) as database:
            try:
                # Read/write is confined to our private copy so SQLite can
                # recover WAL and create its own SHM without touching the source.
                connection = sqlite3.connect(database.as_uri() + '?mode=rw', uri=True)
                try:
                    columns = {row[1] for row in connection.execute('PRAGMA table_info(ZCLOUDRECORDING)')}
                    # Only fixed SQL identifiers are used; older stores lack this
                    # optional field. Never use the sorting label as display text.
                    display_title = 'ZENCRYPTEDTITLE' if 'ZENCRYPTEDTITLE' in columns else 'NULL'
                    rows = connection.execute(QUERY.format(display_title=display_title)).fetchall()
                finally:
                    connection.close()
            except sqlite3.Error as error:
                raise SnapshotError('讀不懂語音備忘錄的錄音清單') from error
        result, seen = [], set()
        for display_title, label, date, duration, path in rows:
            if not _plain_audio_name(path) or path in seen:
                continue
            seen.add(path)
            audio = recordings / path
            availability, byte_count = _availability(directory_fd, path)
            try:
                if label is not None and not isinstance(label, str):
                    raise ValueError('label must be text')
                if duration is not None and not math.isfinite(duration):
                    raise ValueError('duration must be finite')
                recorded = (APPLE_EPOCH + datetime.timedelta(seconds=date)).astimezone() if date is not None else None
                rounded_duration = round(duration or 0, 1)
            except (TypeError, ValueError, OverflowError) as error:
                raise SnapshotError('語音備忘錄清單的標題、日期或時長格式無法讀取') from error
            # Despite its name, this field can contain plain display text. Do not
            # decode blobs or apply the legacy timestamp-label heuristic to it.
            memo_title = (display_title if isinstance(display_title, str) and display_title.strip()
                          else title(label, recorded, audio.stem))
            result.append({'title': memo_title,
                           'recorded_at': recorded.isoformat(timespec='seconds') if recorded else None,
                           'duration': rounded_duration, 'path': str(audio),
                           'id': hashlib.sha256(os.fsencode(audio)).hexdigest(),
                           'availability': availability, 'byte_count': byte_count})
        return result
    finally:
        os.close(directory_fd)


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
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 4


if __name__ == '__main__':
    sys.exit(main())
