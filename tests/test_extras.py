import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(
    0, str(Path(__file__).parents[1] / 'resources' / 'lib'))

import extras  # noqa: E402


SEGMENTS_RESPONSE = [
    {'videoID': 'other', 'segments': [
        {'segment': [0, 5], 'category': 'sponsor', 'actionType': 'skip'}]},
    {'videoID': 'vid1', 'segments': [
        {'segment': [60, 90], 'category': 'sponsor',
         'actionType': 'skip', 'UUID': 'b'},
        {'segment': [0, 12], 'category': 'intro',
         'actionType': 'skip', 'UUID': 'a'},
        {'segment': [100, 100], 'category': 'poi_highlight',
         'actionType': 'skip', 'UUID': 'c'},
        {'segment': [200, 210], 'category': 'chapter',
         'actionType': 'chapter', 'UUID': 'd'},
    ]},
]


class SegmentTests(unittest.TestCase):
    def test_parse_filters_and_sorts(self):
        segments = extras.parse_segments(SEGMENTS_RESPONSE, 'vid1')
        self.assertEqual(['intro', 'sponsor'],
                         [s['category'] for s in segments])
        self.assertEqual((0.0, 12.0),
                         (segments[0]['start'], segments[0]['end']))

    def test_segments_need_finite_times(self):
        # JSON 1e309 is an infinite float; a skip to infinity ends the video.
        data = [{'videoID': 'vid1', 'segments': [
            {'segment': [10, json.loads('1e309')], 'category': 'sponsor'},
            {'segment': ['NaN', 20], 'category': 'sponsor'},
            {'segment': [-5, 3], 'category': 'intro'},
            # float() of an int above the float range raises OverflowError
            {'segment': [10, 10 ** 400], 'category': 'sponsor'},
            {'segment': [30, 40], 'category': 'outro'}]}]
        self.assertEqual(['outro'], [s['category'] for s in extras.parse_segments(data, 'vid1')])

    def test_skip_once_while_inside(self):
        skips = extras.SegmentSkips(
            extras.parse_segments(SEGMENTS_RESPONSE, 'vid1'))
        self.assertIsNone(skips.check(30))
        self.assertEqual('intro', skips.check(5)['category'])
        # An adaptive stream resumes at a chunk start short of the target,
        # and getTime() can lag the seek; neither may skip again.
        self.assertIsNone(skips.check(5))
        self.assertIsNone(skips.check(8))
        self.assertIsNone(extras.SegmentSkips([]).check(5))

    def test_landing_near_the_end_is_past_it(self):
        skips = extras.SegmentSkips(
            extras.parse_segments(SEGMENTS_RESPONSE, 'vid1'))
        self.assertIsNone(skips.check(11.8))

    def test_rearms_after_leaving(self):
        skips = extras.SegmentSkips(
            extras.parse_segments(SEGMENTS_RESPONSE, 'vid1'))
        self.assertEqual('sponsor', skips.check(61)['category'])
        self.assertIsNone(skips.check(88))
        self.assertIsNone(skips.check(91))
        # The viewer seeks back before the segment and plays into it.
        self.assertIsNone(skips.check(50))
        self.assertEqual('sponsor', skips.check(61)['category'])

    def test_overlapping_segments_skip_to_the_furthest_end(self):
        skips = extras.SegmentSkips([
            {'category': 'preview', 'start': 0.0, 'end': 6.426, 'uuid': 'p'},
            {'category': 'intro', 'start': 0.0, 'end': 6.147, 'uuid': 'i'},
        ])
        self.assertEqual(6.426, skips.check(0)['end'])
        self.assertIsNone(skips.check(4.0))

    def test_ends_video(self):
        # Outro of 8ZYhuvIv1pA: SponsorBlock ends the segment at the duration.
        outro = {'category': 'outro', 'start': 139.837, 'end': 147.841}
        self.assertTrue(extras.ends_video(outro, 147.841))
        self.assertTrue(extras.ends_video(outro, 148.5))
        self.assertFalse(extras.ends_video(outro, 600))
        # Unknown duration: seek as usual.
        self.assertFalse(extras.ends_video(outro, 0))

    def test_fetch_uses_hash_prefix(self):
        seen = {}

        def opener(url):
            seen['url'] = url
            return json.dumps(SEGMENTS_RESPONSE).encode('utf-8')

        segments = extras.fetch_segments('vid1', ('sponsor',), opener)
        prefix = hashlib.sha256(b'vid1').hexdigest()[:4]
        self.assertIn('/api/skipSegments/' + prefix, seen['url'])
        self.assertEqual(2, len(segments))


class CategoryTests(unittest.TestCase):
    def test_master_toggle_off(self):
        self.assertEqual([], extras.categories_for({'sponsorblock': False}))

    def test_defaults_cover_all_groups(self):
        categories = extras.categories_for({})
        for expected in ('sponsor', 'intro', 'interaction', 'filler'):
            self.assertIn(expected, categories)

    def test_group_toggle(self):
        categories = extras.categories_for({
            'sponsorblock': True, 'sponsorblock_sponsor': False,
            'sponsorblock_intro_outro': True,
            'sponsorblock_interaction': False,
            'sponsorblock_filler': False})
        self.assertEqual(['intro', 'outro', 'preview', 'hook'], categories)


class DeArrowTests(unittest.TestCase):
    def test_parse_branding(self):
        # Shape of a live sponsor.ajay.app/api/branding answer.
        title, thumb = extras.parse_branding({
            'titles': [
                {'title': 'Orig', 'original': True, 'votes': 5},
                {'title': 'Better Title', 'original': False, 'votes': 3}],
            'thumbnails': [
                {'timestamp': None, 'original': True, 'votes': 9},
                {'timestamp': 3.92349, 'original': False, 'locked': True}]}, 'dQw4w9WgXcQ')
        self.assertEqual('Better Title', title)
        self.assertEqual('https://dearrow-thumb.ajay.app/api/v1/getThumbnail'
                         '?videoID=dQw4w9WgXcQ&time=3.92349', thumb)

    def test_thumbnail_without_a_timestamp_is_skipped(self):
        self.assertEqual((None, None), extras.parse_branding(
            {'titles': [], 'thumbnails': [{'original': False, 'locked': True}]}, 'abc'))

    def test_branding_comes_from_the_api_host(self):
        from unittest.mock import patch
        with patch.object(extras, '_default_get', return_value=b'{}') as get:
            extras.fetch_branding('abc')
        self.assertEqual('https://sponsor.ajay.app/api/branding?videoID=abc', get.call_args.args[0])

    def test_negative_votes_do_not_win(self):
        title, thumb = extras.parse_branding({
            'titles': [{'title': 'Bad', 'original': False, 'votes': -2}],
            'thumbnails': []})
        self.assertIsNone(title)
        self.assertIsNone(thumb)

    def test_branding_lookup_has_a_short_deadline(self):
        from unittest.mock import patch
        with patch.object(extras, '_default_get', return_value=b'{}') as get:
            extras.fetch_branding('abc')
        self.assertLessEqual(get.call_args.kwargs['timeout'], 2)
        with patch.object(extras, '_default_get', side_effect=TimeoutError('slow')):
            self.assertEqual([{'type': 'video', 'id': 'abc', 'title': 'Kept'}],
                             extras.apply_dearrow([{'type': 'video', 'id': 'abc', 'title': 'Kept'}]))

    def test_apply_dearrow_isolates_failures(self):
        items = [
            {'type': 'video', 'id': 'ok', 'title': 'Clickbait',
             'thumbnail': 'old.jpg'},
            {'type': 'video', 'id': 'boom', 'title': 'Keep Me',
             'thumbnail': 'keep.jpg'},
            {'type': 'channel', 'id': 'UC1', 'title': 'Chan'},
        ]

        def fetch(video_id):
            if video_id == 'boom':
                raise RuntimeError('network down')
            return 'Honest Title', 'new.jpg'

        result = extras.apply_dearrow(items, fetch)
        self.assertEqual('Honest Title', result[0]['title'])
        self.assertEqual('new.jpg', result[0]['thumbnail'])
        self.assertEqual('Keep Me', result[1]['title'])
        self.assertEqual('Chan', result[2]['title'])
        # Inputs are not mutated.
        self.assertEqual('Clickbait', items[0]['title'])


class VotesTests(unittest.TestCase):
    def test_parse_votes(self):
        self.assertEqual(
            {'likes': 10, 'dislikes': 2, 'rating': 4.5},
            extras.parse_votes(
                {'likes': 10, 'dislikes': 2, 'rating': 4.5}))
        self.assertIsNone(extras.parse_votes(None))


if __name__ == '__main__':
    unittest.main()
