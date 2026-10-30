"""Failure modes of the local library: store files, caches, imports and feeds."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'resources' / 'lib'))
import library  # noqa: E402

CHANNEL = 'UC' + 'a' * 22
OTHER = 'UC' + 'b' * 22


def video(video_id, **fields):
    return dict({'type': 'video', 'id': video_id, 'title': video_id}, **fields)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / 'profile'
        self.store = library.Store(str(self.dir))

    def test_missing_directory_and_file_read_as_empty_and_save_creates_them(self):
        self.assertEqual([], self.store.load('history'))
        self.store.add('watch_later', video('v1'))
        self.assertEqual(['v1'], [e['id'] for e in self.store.load('watch_later')])
        self.assertEqual([], [p.name for p in self.dir.iterdir() if p.suffix == '.tmp'])

    def test_corrupt_or_foreign_json_is_kept_aside_and_reads_empty(self):
        self.dir.mkdir()
        for content in ('{not json', '{"a": 1}'):
            (self.dir / 'history.json').write_text(content)
            self.assertEqual([], self.store.load('history'))
            self.assertEqual(content, (self.dir / 'history.json.bad').read_text())
        self.store.add('history', video('v1'))
        self.assertEqual(1, len(self.store.load('history')))

    def test_entries_without_an_id_are_dropped(self):
        self.dir.mkdir()
        (self.dir / 'watch_later.json').write_text(json.dumps([{'id': 'ok'}, {'title': 'x'}, 'str', None]))
        self.assertEqual([{'id': 'ok'}], self.store.load('watch_later'))

    def test_unknown_list_name_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.load('../settings')

    def test_add_moves_duplicates_to_front_and_caps(self):
        for n in range(library.LIMITS['searches'] + 5):
            self.store.add('searches', {'id': 'query %d' % n})
        self.store.add('searches', {'id': 'QUERY 10'})
        entries = self.store.load('searches')
        self.assertEqual(library.LIMITS['searches'], len(entries))
        self.assertEqual('QUERY 10', entries[0]['id'])
        self.assertEqual(1, sum(e['id'].casefold() == 'query 10' for e in entries))
        self.store.add('watch_later', video('Ab'))
        self.store.add('watch_later', video('aB'))
        self.assertEqual(2, len(self.store.load('watch_later')), 'video IDs are case-sensitive')

    def test_remove_absent_and_clear(self):
        self.store.add('watch_later', video('v1'))
        self.store.remove('watch_later', 'missing')
        self.store.remove('watch_later', 'v1')
        self.assertEqual([], self.store.load('watch_later'))
        self.store.add('history', video('v2'))
        self.store.clear('history')
        self.assertEqual([], self.store.load('history'))

    def test_unicode_round_trip(self):
        self.store.add('searches', {'id': 'Ünïcødé 日本'})
        self.assertEqual('Ünïcødé 日本', library.Store(str(self.dir)).load('searches')[0]['id'])

    def test_progress_creates_updates_and_clamps(self):
        self.store.record_progress(video('v1', duration=100), 40.4, 100, now=10)
        self.store.record_progress(video('v2'), -3, 0, now=20)
        self.store.record_progress(video('v1'), 55, 100, now=30)
        entries = self.store.load('history')
        self.assertEqual(['v1', 'v2'], [e['id'] for e in entries])
        self.assertEqual((55, 100, 30), (entries[0]['position'], entries[0]['total'], entries[0]['watched_at']))
        self.assertEqual(0, entries[1]['position'])

    def test_progress_without_a_position_keeps_the_resume_point(self):
        self.store.record_progress(video('v1'), 1200, 3000, now=1)
        self.store.record_progress(video('v1', duration=3000), now=2)
        self.store.record_progress(video('v2', duration=50), now=3)
        entries = {e['id']: e for e in self.store.load('history')}
        self.assertEqual((1200, 3000, 2), (entries['v1']['position'], entries['v1']['total'],
                                            entries['v1']['watched_at']))
        self.assertEqual((0, 50), (entries['v2']['position'], entries['v2']['total']))

    def test_progress_updates_only_existing_entries_when_asked(self):
        self.store.record_progress(video('v1'), 10, 100, create=False)
        self.assertEqual([], self.store.load('history'))
        self.store.record_progress(video('v1'), 10, 100)
        self.store.remove('history', 'v1')
        self.store.record_progress(video('v1'), 20, 100, create=False)
        self.assertEqual([], self.store.load('history'), 'a removed video stays removed')

    def test_concurrent_writers_keep_every_entry(self):
        script = ('import sys; sys.path.insert(0, %r); import library; s = library.Store(%r)\n'
                  'for n in range(25): s.add("history", {"id": sys.argv[1] + str(n)})\n'
                  % (str(Path(library.__file__).parent), str(self.dir)))
        workers = [subprocess.Popen([sys.executable, '-c', script, name], stderr=subprocess.PIPE)
                   for name in 'abcd']
        errors = [worker.communicate()[1] for worker in workers]
        self.assertEqual([b''] * 4, errors)
        self.assertEqual(100, len(self.store.load('history')))
        self.assertFalse((self.dir / 'history.json.bad').exists())
        self.assertEqual(['history.json'], sorted(p.name for p in self.dir.iterdir() if p.suffix != '.lock'))

    def test_legacy_follows_migrate_once_and_skip_invalid_ids(self):
        self.store.migrate_follows(lambda: CHANNEL + ', bad-id ,' + OTHER)
        self.assertEqual([CHANNEL, OTHER], [e['id'] for e in self.store.load('follows')])
        self.store.remove('follows', CHANNEL)
        self.store.migrate_follows(self.fail)
        self.assertEqual([OTHER], [e['id'] for e in self.store.load('follows')])

    def test_legacy_setting_reads_old_profile_values(self):
        self.assertEqual('', library.legacy_setting(str(self.dir), 'followed_channels'))
        self.dir.mkdir()
        (self.dir / 'settings.xml').write_text('<settings version="2"><setting id="followed_channels">'
                                               + CHANNEL + '</setting><setting id="x" /></settings>')
        self.assertEqual(CHANNEL, library.legacy_setting(str(self.dir), 'followed_channels'))
        self.assertEqual('', library.legacy_setting(str(self.dir), 'x'))
        (self.dir / 'settings.xml').write_text('<settings')
        self.assertEqual('', library.legacy_setting(str(self.dir), 'followed_channels'))

    def test_import_keeps_existing_titles_and_adds_new_channels(self):
        self.store.add('follows', {'id': CHANNEL, 'title': 'Kept', 'thumbnail': 'art'})
        added = self.store.import_follows([{'id': CHANNEL, 'title': 'New'}, {'id': OTHER, 'title': 'Other'}])
        self.assertEqual(1, added)
        follows = {e['id']: e for e in self.store.load('follows')}
        self.assertEqual(('Kept', 'art'), (follows[CHANNEL]['title'], follows[CHANNEL]['thumbnail']))
        self.assertEqual('Other', follows[OTHER]['title'])

    def test_follow_cap_matches_the_channel_limit_and_import_counts_only_kept(self):
        self.assertEqual(library.innertube.MAX_CHANNELS, library.LIMITS['follows'])
        channels = [{'id': 'UC' + str(n).zfill(22), 'title': str(n)}
                    for n in range(library.LIMITS['follows'] + 3)]
        self.assertEqual(library.LIMITS['follows'], self.store.import_follows(channels))
        self.assertEqual(0, self.store.import_follows(channels[-2:]))


class HistoryViewTests(unittest.TestCase):
    def test_continue_needs_real_progress_short_of_the_end(self):
        history = [
            video('done', position=95, total=100), video('started', position=10, total=100),
            video('middle', position=50, total=100), video('live', position=50, total=100, is_live=True),
            video('unknown', position=50, total=0)]
        self.assertEqual(['middle'], [e['id'] for e in library.continue_items(history)])
        self.assertEqual({'middle': (50, 100), 'started': (10, 100)},
                         library.resume_points(history))

    def test_recommended_interleaves_related_and_skips_watched(self):
        history = [video('h1'), video('h2', is_live=True), video('h3'), video('h4'), video('h5')]
        related = {'h1': [video('a'), video('h3'), video('b')], 'h3': [video('a'), video('c')],
                   'h4': [video('d')]}
        calls = []
        def fetch(video_id):
            calls.append(video_id)
            if video_id == 'h4':
                raise library.innertube.InnertubeError('offline')
            return related[video_id]
        items = library.recommended(history, fetch)
        self.assertEqual(['a', 'b', 'c'], sorted(i['id'] for i in items))
        self.assertEqual('a', items[0]['id'])
        self.assertEqual(['h1', 'h3', 'h4'], sorted(calls), 'three newest non-live entries')
        self.assertEqual([], library.recommended([], fetch))


class TakeoutTests(unittest.TestCase):
    def test_takeout_csv_with_bom_quotes_blanks_and_bad_rows(self):
        text = ('﻿Channel Id,Channel Url,Channel Title\n'
                + CHANNEL + ',http://www.youtube.com/channel/' + CHANNEL + ',"Comma, Inc"\n\n'
                + 'not-an-id,http://x,Bad\n'
                + OTHER + ',http://www.youtube.com/channel/' + OTHER + ',Other\n'
                + CHANNEL + ',dup,Dup\n')
        self.assertEqual([{'id': CHANNEL, 'title': 'Comma, Inc'}, {'id': OTHER, 'title': 'Other'}],
                         library.parse_takeout_csv(text))

    def test_files_without_the_takeout_header_are_rejected(self):
        for text in ('', 'name,url\nx,y\n'):
            with self.assertRaises(ValueError):
                library.parse_takeout_csv(text)
        self.assertEqual([], library.parse_takeout_csv('Channel Id,Channel Url,Channel Title\n'))


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = library.Cache(self.tmp.name + '/cache')
        self.calls = []

    def fetch(self, value):
        def run():
            self.calls.append(value)
            return value
        return run

    def test_fresh_value_is_reused_and_stale_value_refetched(self):
        self.assertEqual(1, self.cache.get('k', 60, self.fetch(1), now=0))
        self.assertEqual(1, self.cache.get('k', 60, self.fetch(2), now=59))
        self.assertEqual(2, self.cache.get('k', 60, self.fetch(2), now=61))
        self.assertEqual([1, 2], self.calls)

    def test_none_is_cached_and_failures_are_not(self):
        self.assertIsNone(self.cache.get('k', 60, self.fetch(None), now=0))
        self.assertIsNone(self.cache.get('k', 60, self.fetch('x'), now=1))
        def broken():
            raise OSError('offline')
        with self.assertRaises(OSError):
            self.cache.get('other', 60, broken, now=0)
        self.assertEqual('y', self.cache.get('other', 60, self.fetch('y'), now=1))

    def test_prune_removes_only_old_entries(self):
        self.cache.get('old', 60, self.fetch(1), now=0)
        self.cache.get('new', 60, self.fetch(2), now=0)
        directory = Path(self.tmp.name, 'cache')
        old, new = (directory / (hashlib.sha1(key.encode()).hexdigest() + '.json') for key in ('old', 'new'))
        os.utime(old, (1000, 1000))
        os.utime(new, (9000, 9000))
        self.cache.prune(5000, now=10000)
        self.assertEqual([new.name], [path.name for path in directory.iterdir()])
        library.Cache(self.tmp.name + '/absent').prune(1)

    def test_unwritable_cache_still_returns_the_value(self):
        Path(self.tmp.name, 'cache').write_text('a file where the directory should be')
        self.assertEqual(5, self.cache.get('k', 60, self.fetch(5), now=0))

    def test_corrupt_file_and_hostile_keys(self):
        self.cache.get('../../escape', 60, self.fetch(1), now=0)
        files = list(Path(self.tmp.name, 'cache').iterdir())
        self.assertEqual(1, len(files))
        files[0].write_text('garbage')
        self.assertEqual(3, self.cache.get('../../escape', 60, self.fetch(3), now=1))


if __name__ == '__main__':
    unittest.main()
