"""Voice Memos listing against a throwaway CloudRecordings.db."""
import datetime
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('wordprint_voice_memos', Path(__file__).parents[1] / 'scripts' / 'voice_memos.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class VoiceMemoTests(unittest.TestCase):
    def test_unnamed_memo_titles_use_local_recording_time(self):
        when = datetime.datetime(2026, 10, 15, 6, 1, 31, tzinfo=datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            connection = sqlite3.connect(Path(temp) / 'CloudRecordings.db')
            connection.execute('CREATE TABLE ZCLOUDRECORDING (ZCUSTOMLABEL, ZDATE, ZDURATION, ZPATH, ZEVICTIONDATE)')
            seconds = (when - v.APPLE_EPOCH).total_seconds()
            connection.executemany('INSERT INTO ZCLOUDRECORDING VALUES (?, ?, 1.0, ?, NULL)',
                                   [('2026-10-15T06:01:31Z', seconds, 'a.m4a'), ('週會', seconds - 60, 'b.m4a')])
            connection.commit()
            connection.close()
            memos = v.memos(Path(temp))
        local = when.astimezone()
        self.assertEqual([m['title'] for m in memos], [f'語音備忘錄 {local:%m-%d %H:%M}', '週會'])
        taipei = datetime.timezone(datetime.timedelta(hours=8))
        self.assertEqual(v.title('2026-10-15T06:01:31Z', when.astimezone(taipei), 'x'), '語音備忘錄 10-15 14:01')
        self.assertEqual(v.title('2026-10-15 讀書會', when, 'x'), '2026-10-15 讀書會')


if __name__ == '__main__':
    unittest.main()
