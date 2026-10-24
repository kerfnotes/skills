"""Voice Memos listing against a throwaway CloudRecordings.db."""
import datetime
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

spec = importlib.util.spec_from_file_location('wordprint_voice_memos', Path(__file__).parents[1] / 'scripts' / 'voice_memos.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class VoiceMemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'CloudRecordings.db'
        self.wal = self.root / 'CloudRecordings.db-wal'

    def store(self, rows=(), wal=True):
        connection = sqlite3.connect(self.db)
        self.addCleanup(connection.close)
        if wal:
            self.assertEqual(connection.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
            connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('CREATE TABLE ZCLOUDRECORDING (ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH, ZEVICTIONDATE)')
        connection.executemany('INSERT INTO ZCLOUDRECORDING VALUES (?, ?, ?, ?, ?)', rows)
        connection.commit()
        return connection

    def row(self, name='a.m4a', label='測試', date=100, deleted=None):
        return label, date, 1.0, name, deleted

    def test_optional_display_title_overrides_timestamp_and_old_label(self):
        connection = self.store([
            self.row(label='2026-01-02T03:04:05Z', date=200),
            self.row('b.qta', label='合成舊標題', date=100),
        ])
        before = v.memos(self.root)
        connection.execute('ALTER TABLE ZCLOUDRECORDING ADD COLUMN ZENCRYPTEDTITLE')
        connection.executemany('UPDATE ZCLOUDRECORDING SET ZENCRYPTEDTITLE=? WHERE ZPATH=?',
                               [('合成專案進度', 'a.m4a'), ('合成重新命名', 'b.qta')])
        connection.commit()
        after = v.memos(self.root)
        self.assertEqual([row['title'] for row in after], ['合成專案進度', '合成重新命名'])
        self.assertEqual([{k: value for k, value in row.items() if k != 'title'} for row in after],
                         [{k: value for k, value in row.items() if k != 'title'} for row in before])
        connection.execute("UPDATE ZCLOUDRECORDING SET ZENCRYPTEDTITLE='合成再次改名' WHERE ZPATH='a.m4a'")
        connection.commit()
        renamed = v.memos(self.root)
        self.assertEqual(renamed[0]['title'], '合成再次改名')
        self.assertEqual([row['id'] for row in renamed], [row['id'] for row in before])

    def test_optional_display_title_invalid_values_keep_legacy_fallback(self):
        labels = ['合成舊標題', '2026-01-02T03:04:05Z', None, '']
        connection = self.store([self.row(f'{index}.m4a', label=label, date=index)
                                 for index, label in enumerate(labels)])
        legacy = v.memos(self.root)
        self.assertEqual(legacy[0]['title'], '3')
        self.assertEqual(legacy[-1]['title'], '合成舊標題')
        connection.execute('ALTER TABLE ZCLOUDRECORDING ADD COLUMN ZENCRYPTEDTITLE')
        connection.execute('ALTER TABLE ZCLOUDRECORDING ADD COLUMN ZCUSTOMLABELFORSORTING')
        connection.execute("UPDATE ZCLOUDRECORDING SET ZCUSTOMLABELFORSORTING='合成排序用名稱'")
        for value in (None, '', '   ', 123, 1.5, b'opaque title bytes', b''):
            with self.subTest(optional_title=value):
                connection.execute('UPDATE ZCLOUDRECORDING SET ZENCRYPTEDTITLE=?', (value,))
                connection.commit()
                self.assertEqual(v.memos(self.root), legacy)

    def test_optional_display_title_is_not_reinterpreted_as_legacy_timestamp(self):
        connection = self.store([self.row(label='合成舊標題')])
        connection.execute('ALTER TABLE ZCLOUDRECORDING ADD COLUMN ZENCRYPTEDTITLE')
        connection.execute("UPDATE ZCLOUDRECORDING SET ZENCRYPTEDTITLE='2026-01-02T03:04:05Z'")
        connection.commit()
        self.assertEqual(v.memos(self.root)[0]['title'], '2026-01-02T03:04:05Z')

    def test_unnamed_memo_titles_use_local_recording_time(self):
        when = datetime.datetime(2026, 10, 15, 6, 1, 31, tzinfo=datetime.timezone.utc)
        seconds = (when - v.APPLE_EPOCH).total_seconds()
        self.store([self.row(label='2026-10-15T06:01:31Z', date=seconds),
                    self.row('b.m4a', label='週會', date=seconds - 60)])
        memos = v.memos(self.root)
        local = when.astimezone()
        self.assertEqual([m['title'] for m in memos], [f'語音備忘錄 {local:%m-%d %H:%M}', '週會'])
        taipei = datetime.timezone(datetime.timedelta(hours=8))
        self.assertEqual(v.title('2026-10-15T06:01:31Z', when.astimezone(taipei), 'x'), '語音備忘錄 10-15 14:01')
        self.assertEqual(v.title('2026-10-15 讀書會', when, 'x'), '2026-10-15 讀書會')

    def test_wal_rows_availability_and_stable_path_id(self):
        connection = self.store([self.row(), self.row('missing.qta', date=101),
                                 self.row('deleted.m4a', deleted=1)])
        audio = self.root / 'a.m4a'
        audio.write_bytes(b'synthetic audio placeholder')
        first = v.memos(self.root)
        self.assertIsInstance(first, list)
        self.assertEqual([m['availability'] for m in first], ['missing', 'local'])
        self.assertEqual([m['byte_count'] for m in first], [None, audio.stat().st_size])
        self.assertEqual(first[1]['id'], hashlib.sha256(os.fsencode(audio)).hexdigest())
        self.assertEqual(first[1]['path'], str(audio))
        connection.execute("UPDATE ZCLOUDRECORDING SET ZCUSTOMLABEL='改名' WHERE ZPATH='a.m4a'")
        connection.commit()
        audio.unlink()
        second = v.memos(self.root)
        self.assertEqual(second[1]['id'], first[1]['id'])
        self.assertEqual(second[1]['availability'], 'missing')

    def test_only_plain_audio_names_and_unique_paths_are_listed(self):
        invalid = ['../outside.m4a', '/outside.m4a', 'folder/a.qta', '.hidden.m4a',
                   'a.wav', 'a.m4a/..', 'a\\b.m4a', 'a\x00.m4a', '', None, 123]
        self.store([self.row(name, date=index) for index, name in enumerate(invalid)]
                   + [self.row('UPPER.M4A'), self.row('UPPER.M4A'), self.row('ok.qta')])
        rows = v.memos(self.root)
        self.assertEqual({Path(row['path']).name for row in rows}, {'UPPER.M4A', 'ok.qta'})
        self.assertEqual(len(rows), 2)

    def test_symlinks_directories_and_denied_audio_are_unreadable(self):
        self.store([self.row(name) for name in ('link.m4a', 'broken.m4a', 'dir.qta', 'denied.m4a')])
        (self.root / 'link.m4a').symlink_to(self.db)
        (self.root / 'broken.m4a').symlink_to(self.root / 'absent')
        (self.root / 'dir.qta').mkdir()
        (self.root / 'denied.m4a').write_bytes(b'fake')
        (self.root / 'denied.m4a').chmod(0)
        self.addCleanup((self.root / 'denied.m4a').chmod, 0o600)
        rows = v.memos(self.root)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row['availability'] == 'unreadable' and row['byte_count'] is None for row in rows))

    def test_listing_never_opens_audio_or_touches_source_shm(self):
        connection = self.store([self.row()])
        connection.execute('ALTER TABLE ZCLOUDRECORDING ADD COLUMN ZENCRYPTEDTITLE')
        connection.execute("UPDATE ZCLOUDRECORDING SET ZENCRYPTEDTITLE='合成顯示標題'")
        connection.commit()
        (self.root / 'a.m4a').write_bytes(b'fake')
        original_open, original_stat, original_access = os.open, os.stat, os.access

        def guard(function, opening=False):
            def checked(path, *args, **kwargs):
                if kwargs.get('dir_fd') is not None:
                    self.assertNotEqual(path, 'CloudRecordings.db-shm')
                    if opening:
                        self.assertIn(path, ('CloudRecordings.db', 'CloudRecordings.db-wal'))
                        self.assertEqual(args[0] & os.O_ACCMODE, os.O_RDONLY)
                return function(path, *args, **kwargs)
            return checked

        with patch.object(v.os, 'open', side_effect=guard(original_open, True)), \
                patch.object(v.os, 'stat', side_effect=guard(original_stat)), \
                patch.object(v.os, 'access', side_effect=guard(original_access)):
            row = v.memos(self.root)[0]
            self.assertEqual(row['availability'], 'local')
            self.assertEqual(row['title'], '合成顯示標題')

    def test_sqlite_only_opens_private_0700_snapshot_and_sources_stay_identical(self):
        self.store([self.row()])
        sources = list(self.root.iterdir())

        def signatures():
            return {path.name: (path.read_bytes(), v._signature(path.stat())) for path in sources}

        before = signatures()
        original_connect = sqlite3.connect
        snapshots = []

        def connect(database_uri, **kwargs):
            path = Path(unquote(urlsplit(database_uri).path))
            self.assertNotEqual(path.parent, self.root)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse((path.parent / 'CloudRecordings.db-shm').exists())
            snapshots.append(path.parent)
            return original_connect(database_uri, **kwargs)

        with patch.object(v.sqlite3, 'connect', side_effect=connect):
            self.assertEqual(len(v.memos(self.root)), 1)
        self.assertEqual(before, signatures())
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(snapshots[0].exists())

    def test_copy_order_and_retry_after_commit_between_copies(self):
        connection = self.store([self.row()])
        original_copy = v._copy_file
        copied = []

        def copy(directory_fd, name, destination, expected):
            original_copy(directory_fd, name, destination, expected)
            copied.append(name)
            if len(copied) == 1:
                connection.execute('INSERT INTO ZCLOUDRECORDING VALUES (?, ?, ?, ?, ?)', self.row('new.qta', date=200))
                connection.commit()

        with patch.object(v, '_copy_file', side_effect=copy):
            rows = v.memos(self.root)
        self.assertEqual(copied, ['CloudRecordings.db-wal', 'CloudRecordings.db'] * 2)
        self.assertEqual([Path(row['path']).name for row in rows], ['new.qta', 'a.m4a'])

    def test_checkpoint_removing_wal_is_retried(self):
        connection = self.store([self.row()])
        original_copy = v._copy_file
        changed = False

        def copy(directory_fd, name, destination, expected):
            nonlocal changed
            original_copy(directory_fd, name, destination, expected)
            if name.endswith('-wal') and not changed:
                changed = True
                connection.close()  # Checkpoint fixture and remove WAL/SHM.

        with patch.object(v, '_copy_file', side_effect=copy):
            self.assertEqual(len(v.memos(self.root)), 1)
        self.assertTrue(changed)
        self.assertFalse(self.wal.exists())

    def test_wal_disappearing_before_open_is_retried(self):
        connection = self.store([self.row()])
        original_copy = v._copy_file
        disappeared = False

        def copy(directory_fd, name, destination, expected):
            nonlocal disappeared
            if name.endswith('-wal') and not disappeared:
                disappeared = True
                connection.close()
            original_copy(directory_fd, name, destination, expected)

        with patch.object(v, '_copy_file', side_effect=copy):
            self.assertEqual(len(v.memos(self.root)), 1)
        self.assertTrue(disappeared)

    def test_wal_header_reset_is_detected_even_with_unchanged_stat_stamps(self):
        connection = self.store([self.row()])
        # Preserve this fixture's WAL on disk while making a copied store that
        # has no live writer. Only synthetic data is ever changed by this test.
        wal_bytes = self.wal.read_bytes()
        connection.close()
        self.wal.write_bytes(wal_bytes)
        original_copy, original_signature = v._copy_file, v._signature
        attempts = []

        def signature(info):
            values = list(original_signature(info))
            values[3:5] = [0, 0]  # Simulate timestamps restored/coarsened by a filesystem.
            return tuple(values)

        def copy(directory_fd, name, destination, expected):
            original_copy(directory_fd, name, destination, expected)
            if name.endswith('-wal'):
                attempts.append(name)
                data = bytearray(self.wal.read_bytes())
                data[16] ^= 1  # WAL salt changes without inode/size changes.
                self.wal.write_bytes(data)

        with patch.object(v, '_signature', side_effect=signature), \
                patch.object(v, '_copy_file', side_effect=copy), \
                patch.object(v.sqlite3, 'connect') as connect:
            with self.assertRaisesRegex(v.SnapshotError, '5 次'):
                v.memos(self.root)
        self.assertEqual(len(attempts), 5)
        connect.assert_not_called()

    def test_continuously_changing_source_stops_after_five_and_cleans_up(self):
        connection = self.store([self.row()])
        original_copy = v._copy_file
        folders, attempts = set(), []

        def copy(directory_fd, name, destination, expected):
            folders.add(destination.parent)
            original_copy(directory_fd, name, destination, expected)
            if name.endswith('-wal'):
                attempts.append(name)
                connection.execute('UPDATE ZCLOUDRECORDING SET ZDATE=ZDATE+1')
                connection.commit()

        with patch.object(v, '_copy_file', side_effect=copy), patch.object(v.sqlite3, 'connect') as connect:
            with self.assertRaisesRegex(v.SnapshotError, '5 次'):
                v.memos(self.root)
        self.assertEqual(len(attempts), 5)
        connect.assert_not_called()
        self.assertTrue(all(not folder.exists() for folder in folders))

    def test_wal_mode_without_wal_and_empty_wal_are_supported(self):
        connection = self.store([self.row()])
        connection.close()
        self.assertFalse(self.wal.exists())
        self.assertEqual(len(v.memos(self.root)), 1)
        self.wal.touch()
        self.assertEqual(len(v.memos(self.root)), 1)

    def test_missing_database_and_directory_raise_not_found(self):
        for root in (self.root, self.root / 'absent'):
            with self.subTest(root=root), self.assertRaises(FileNotFoundError):
                v.memos(root)

    def test_source_db_and_wal_permission_denials_remain_permission_errors(self):
        self.store([self.row()])
        original_open = os.open
        for denied in ('CloudRecordings.db', 'CloudRecordings.db-wal'):
            def open_file(name, *args, **kwargs):
                if name == denied and kwargs.get('dir_fd') is not None:
                    raise PermissionError(13, 'synthetic denial', name)
                return original_open(name, *args, **kwargs)

            with self.subTest(denied=denied), patch.object(v.os, 'open', side_effect=open_file), \
                    self.assertRaises(PermissionError):
                v.memos(self.root)

    def test_database_and_wal_symlinks_are_rejected_without_open(self):
        connection = self.store([self.row()])
        connection.close()
        for path in (self.db, self.wal):
            with self.subTest(path=path):
                saved = self.root / (path.name + '.saved')
                if path.exists():
                    path.rename(saved)
                else:
                    saved.write_bytes(b'fake')
                path.symlink_to(saved)
                with patch.object(v.sqlite3, 'connect') as connect, self.assertRaises(ValueError):
                    v.memos(self.root)
                connect.assert_not_called()
                path.unlink()
                saved.rename(path)

    def test_directory_symlink_is_rejected(self):
        self.store([self.row()])
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            v.memos(alias)

    def test_database_swapped_to_symlink_between_stat_and_open_is_rejected(self):
        connection = self.store([self.row()])
        connection.close()
        original_open = v._open_source
        swapped = False

        def open_source(directory_fd, name):
            nonlocal swapped
            if name == 'CloudRecordings.db' and not swapped:
                swapped = True
                saved = self.root / 'saved.db'
                self.db.rename(saved)
                self.db.symlink_to(saved)
            return original_open(directory_fd, name)

        with patch.object(v, '_open_source', side_effect=open_source), \
                patch.object(v.sqlite3, 'connect') as connect, self.assertRaises(ValueError):
            v.memos(self.root)
        connect.assert_not_called()

    def test_source_fifo_is_rejected_without_blocking(self):
        os.mkfifo(self.db)
        with self.assertRaises(ValueError):
            v.memos(self.root)

    def test_audio_stat_permission_error_is_unreadable(self):
        self.store([self.row()])
        original_stat = os.stat

        def stat_file(name, *args, **kwargs):
            if name == 'a.m4a' and kwargs.get('dir_fd') is not None:
                raise PermissionError(13, 'synthetic denial')
            return original_stat(name, *args, **kwargs)

        with patch.object(v.os, 'stat', side_effect=stat_file):
            self.assertEqual(v.memos(self.root)[0]['availability'], 'unreadable')

    def test_audio_swapped_to_symlink_during_metadata_check_is_unreadable(self):
        self.store([self.row()])
        audio = self.root / 'a.m4a'
        audio.write_bytes(b'fake')

        def access(*args, **kwargs):
            audio.unlink()
            audio.symlink_to(self.db)
            return True

        with patch.object(v.os, 'access', side_effect=access):
            row = v.memos(self.root)[0]
        self.assertEqual((row['availability'], row['byte_count']), ('unreadable', None))

    def test_invalid_row_metadata_is_a_classified_value_error(self):
        connection = self.store([self.row()])
        for label, date, duration in ((123, 100, 1), ('label', 'bad date', 1),
                                      ('label', 100, 'bad duration'), ('label', 100, float('inf'))):
            connection.execute('UPDATE ZCLOUDRECORDING SET ZCUSTOMLABEL=?, ZDATE=?, ZDURATION=?',
                               (label, date, duration))
            connection.commit()
            with self.subTest(label=label, date=date, duration=duration), self.assertRaises(ValueError):
                v.memos(self.root)

    def test_non_wal_mode_is_rejected_without_sqlite_open(self):
        self.store([self.row()], wal=False)
        with patch.object(v.sqlite3, 'connect') as connect, self.assertRaisesRegex(ValueError, 'WAL'):
            v.memos(self.root)
        connect.assert_not_called()

    def test_corrupt_database_and_wal_are_value_errors(self):
        self.db.write_bytes(b'not sqlite')
        with self.assertRaises(ValueError):
            v.memos(self.root)
        self.db.unlink()
        connection = self.store([self.row()])
        connection.close()
        self.wal.write_bytes(b'not a wal header')
        with self.assertRaisesRegex(ValueError, 'WAL'):
            v.memos(self.root)

    def test_unknown_schema_is_value_error(self):
        connection = self.store()
        connection.execute('DROP TABLE ZCLOUDRECORDING')
        connection.commit()
        with self.assertRaises(ValueError):
            v.memos(self.root)

    def test_cli_keeps_missing_empty_list_and_classifies_other_failures(self):
        for error, code in ((FileNotFoundError(), 0), (PermissionError(), 3), (v.SnapshotError('busy'), 4)):
            with self.subTest(error=type(error)), patch.object(v, 'memos', side_effect=error), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                    patch('sys.stderr', new_callable=io.StringIO) as stderr:
                self.assertEqual(v.main(), code)
                if not code:
                    self.assertEqual(json.loads(stdout.getvalue()), [])
                else:
                    self.assertTrue(stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
