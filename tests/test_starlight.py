"""Offline response replays; fixture identities and art are synthetic."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'resources/lib'))
import innertube
import routes

FIXTURES = Path(__file__).parent / 'fixtures'
CHANNEL = 'UC' + 'a' * 22
OTHER = 'UC' + 'b' * 22


def response(name):
    return json.loads((FIXTURES / (name + '.json')).read_text())


class TrailerTests(unittest.TestCase):
    def setUp(self):
        self.items, _ = innertube.parse_listing_response(response('trailers'))

    def test_official_channel_wins_independent_of_result_order(self):
        for items in (self.items, list(reversed(self.items))):
            ranked = innertube.rank_trailers(items, 'Orbit', '2026')
            self.assertEqual(['official001', 'reupload001'],
                             [item['id'] for item in ranked])

    def test_missing_year_is_allowed_but_exact_year_wins(self):
        unknown = dict(self.items[0], id='unknownyear', title='Orbit Official Trailer')
        ranked = innertube.rank_trailers([unknown, self.items[0]], 'Orbit', '2026')
        self.assertEqual('official001', ranked[0]['id'])

    def test_no_matches_empty_title_and_nonvideo(self):
        self.assertEqual([], innertube.rank_trailers(self.items, '', '2026'))
        self.assertEqual([], innertube.rank_trailers(self.items, 'Absent', '2026'))
        self.assertEqual([], innertube.rank_trailers(
            [dict(self.items[0], type='channel')], 'Orbit', '2026'))

    def test_live_upcoming_fan_edits_and_title_substrings_are_rejected(self):
        for change in ({'is_live': True}, {'is_upcoming': True},
                       {'title': 'Orbital 2026 Official Trailer'},
                       {'title': 'Orbit 2026 Official Trailer fan edit'},
                       {'title': 'Orbit 2026 Official Trailer reactions'},
                       {'title': 'Orbit 2026 Official Trailer concept'}):
            self.assertEqual([], innertube.rank_trailers(
                [dict(self.items[0], **change)], 'Orbit', '2026'))

    def test_year_in_media_title_is_not_a_release_year(self):
        item = dict(self.items[0], title='Orbit 2049 Official Trailer (2026)')
        self.assertEqual([item], innertube.rank_trailers([item], 'Orbit 2049', '2026'))

    def test_tie_break_uses_video_id_and_removes_duplicates(self):
        a = dict(self.items[0], id='a')
        z = dict(self.items[0], id='z')
        self.assertEqual(['a', 'z'], [v['id'] for v in innertube.rank_trailers(
            [z, a, a], 'Orbit', '2026')])

    def test_search_uses_existing_transport_and_preserves_locale(self):
        calls = []
        def transport(url, data, headers, timeout):
            calls.append(json.loads(data))
            return json.dumps(response('trailers')).encode()
        items = innertube.find_trailers('Orbit', '2026', 'movie',
                                       hl='fr', gl='CA', opener=transport)
        self.assertEqual('official001', items[0]['id'])
        self.assertEqual('Orbit 2026 movie official trailer', calls[0]['query'])
        self.assertEqual('fr', calls[0]['context']['client']['hl'])


class StarlightRouteTests(unittest.TestCase):
    def test_trailer_parameters_and_lookup_mode(self):
        route = routes.parse_route('/trailer',
            'title=Orbit+%26+Moon&year=2026&imdb=tt123&tmdb=456&media_type=movie&mode=lookup')
        self.assertEqual('trailer', route.action)
        self.assertEqual('Orbit & Moon', route.title)
        self.assertEqual(('2026', 'tt123', '456', 'movie', 'lookup'),
                         (route.year, route.imdb, route.tmdb, route.media_type, route.mode))
        self.assertEqual('play', routes.parse_route('/trailer', 'title=Orbit&year=2026').mode)

    def test_bad_trailer_parameters_fail_before_network(self):
        for query in ('year=2026', 'title=Orbit', 'title=Orbit&year=oops',
                      'title=Orbit&year=2026&mode=bad',
                      'title=Orbit&year=2026&media_type=game'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                routes.parse_route('/trailer', query)

    def test_live_and_follow_routes(self):
        route = routes.parse_route('/live_now', 'channel_ids=' + CHANNEL)
        self.assertEqual('live_now', route.action)
        self.assertEqual(CHANNEL, route.channel_ids)
        route = routes.parse_route('/follow', 'channel_id=' + CHANNEL)
        self.assertEqual('follow', route.action)
        self.assertEqual(CHANNEL, route.channel_id)

    def test_route_url_uses_addon_root(self):
        self.assertEqual('plugin://plugin.video.smarttube/play/?video_id=abc',
            routes.build_url('plugin://plugin.video.smarttube/trailer/', 'play', video_id='abc'))


class LiveTests(unittest.TestCase):
    def test_current_live_badges_and_overlay_exclude_upcoming(self):
        items, _ = innertube.parse_listing_response(response('live'))
        self.assertEqual(['livevideo01', 'overlay0001'],
                         [v['id'] for v in items if v['is_live']])
        self.assertEqual(CHANNEL, items[0]['channel_id'])

    def test_channel_lockup_video_models_preserve_live_flags_and_art(self):
        model = {
            'contentId': 'stream00001', 'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO',
            'metadata': {'lockupMetadataViewModel': {'title': {'content': 'Orbit live'},
                'metadata': {'contentMetadataViewModel': {'metadataRows': [
                    {'metadataParts': [{'text': {'content': '123 watching'}}]}]}}}},
            'contentImage': {'thumbnailViewModel': {
                'image': {'sources': [{'url':'https://example.com/live.jpg', 'width':720}]},
                'overlays': [{'thumbnailBottomOverlayViewModel': {'badges': [
                    {'thumbnailBadgeViewModel': {'text':'LIVE',
                        'badgeStyle':'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE'}}]}}]}}}
        rows, _ = innertube.parse_listing_response({'contents':[{'lockupViewModel':model}]})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['id'], rows[0]['title'], rows[0]['is_live'], rows[0]['thumbnail']),
                         ('stream00001', 'Orbit live', True, 'https://example.com/live.jpg'))
        model['contentImage']['thumbnailViewModel']['overlays'] = []
        rows, _ = innertube.parse_listing_response({'lockupViewModel':model})
        self.assertFalse(rows[0]['is_live'])
        model['contentType'] = 'LOCKUP_CONTENT_TYPE_PLAYLIST'
        self.assertEqual(innertube.parse_listing_response({'lockupViewModel':model})[0], [])
        self.assertEqual(innertube.parse_listing_response({'lockupViewModel':{}})[0], [])

    def test_channel_ids_deduplicate_and_validate(self):
        self.assertEqual([CHANNEL, OTHER], innertube.channel_ids(
            CHANNEL + ', ' + OTHER + '\n' + CHANNEL))
        with self.assertRaises(ValueError):
            innertube.channel_ids('../not-a-channel')
        with self.assertRaises(ValueError):
            innertube.channel_ids(','.join('UC' + str(n).zfill(22) for n in range(26)))

    def test_live_listing_continues_deduplicates_and_reports_failure(self):
        items, _ = innertube.parse_listing_response(response('live'))
        with patch.object(innertube, 'browse', side_effect=[
                ([items[1], items[2]], 'next'),
                ([items[0], items[3]], ''), innertube.InnertubeError('offline')]) as browse:
            live, failures = innertube.live_now([CHANNEL, CHANNEL, OTHER])
        self.assertEqual([CHANNEL], [v['channel_id'] for v in live])
        self.assertEqual([OTHER], failures)
        self.assertEqual('next', browse.call_args_list[1].kwargs['continuation'])
        self.assertEqual('livevideo01', live[0]['id'])

    def test_empty_and_page_limit(self):
        self.assertEqual(([], []), innertube.live_now([]))
        with patch.object(innertube, 'browse', return_value=([], 'repeat')) as browse:
            self.assertEqual(([], []), innertube.live_now([CHANNEL]))
            self.assertLessEqual(browse.call_count, 3)


if __name__ == '__main__':
    unittest.main()
