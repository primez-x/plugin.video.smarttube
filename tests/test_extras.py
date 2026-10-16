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

    def test_segment_at(self):
        segments = extras.parse_segments(SEGMENTS_RESPONSE, 'vid1')
        self.assertEqual('intro',
                         extras.segment_at(segments, 5)['category'])
        self.assertIsNone(extras.segment_at(segments, 30))
        # Just before the end counts as past it (avoids seek loops).
        self.assertIsNone(extras.segment_at(segments, 11.8))
        self.assertIsNone(extras.segment_at([], 5))

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
        title, thumb = extras.parse_branding({
            'titles': [
                {'title': 'Orig', 'original': True, 'votes': 5},
                {'title': 'Better Title', 'original': False, 'votes': 3}],
            'thumbnails': [
                {'thumbnailURL': 'https://x.test/t.jpg',
                 'original': False, 'locked': True}]})
        self.assertEqual('Better Title', title)
        self.assertEqual('https://x.test/t.jpg', thumb)

    def test_negative_votes_do_not_win(self):
        title, thumb = extras.parse_branding({
            'titles': [{'title': 'Bad', 'original': False, 'votes': -2}],
            'thumbnails': []})
        self.assertIsNone(title)
        self.assertIsNone(thumb)

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
