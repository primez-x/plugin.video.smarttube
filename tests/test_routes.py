import sys
from pathlib import Path
import unittest

sys.path.insert(
    0, str(Path(__file__).parents[1] / 'resources' / 'lib'))

import routes  # noqa: E402


class YoutubeCompatRouteTests(unittest.TestCase):
    """Standard YouTube URL shapes accepted by Starlight."""

    def test_starlight_search(self):
        route = routes.parse_route('/search/', 'q=Some%20Movie&search_type=notvalid')
        self.assertEqual('search', route.action)
        self.assertEqual('Some Movie', route.query)

    def test_skin_info_search(self):
        route = routes.parse_route(
            '/kodion/search/query/', 'q=Artist%20Title&search_type=notvalid')
        self.assertEqual('search', route.action)
        self.assertEqual('Artist Title', route.query)

    def test_skin_search_path(self):
        route = routes.parse_route('/search/', 'q=hello')
        self.assertEqual('search', route.action)

    def test_play_video(self):
        route = routes.parse_route('/play/', 'video_id=dQw4w9WgXcQ')
        self.assertEqual('play', route.action)
        self.assertEqual('dQw4w9WgXcQ', route.video_id)

    def test_play_playlist_opens_listing(self):
        route = routes.parse_route('/play/', 'playlist_id=PLabc')
        self.assertEqual('playlist', route.action)
        self.assertEqual('PLabc', route.playlist_id)

    def test_play_channel_live(self):
        route = routes.parse_route('/play/', 'channel_id=UCabc&live=1')
        self.assertEqual('play_channel', route.action)
        self.assertEqual('UCabc', route.channel_id)
        self.assertTrue(route.live)

    def test_channel_and_playlist_paths(self):
        self.assertEqual(
            'channel', routes.parse_route('/channel/UCabc/').action)
        self.assertEqual(
            'UCabc', routes.parse_route('/channel/UCabc/').channel_id)
        route = routes.parse_route('/channel/UCabc/playlist/PLxyz/')
        self.assertEqual('playlist', route.action)
        self.assertEqual('PLxyz', route.playlist_id)
        route = routes.parse_route('/playlist/PLxyz/')
        self.assertEqual('playlist', route.action)

    def test_home(self):
        self.assertEqual('home', routes.parse_route('/').action)
        self.assertEqual('home', routes.parse_route('').action)

    def test_continuation_is_carried(self):
        route = routes.parse_route('/search/', 'q=x&continuation=tok123')
        self.assertEqual('tok123', route.continuation)


class BuildUrlTests(unittest.TestCase):
    BASE = 'plugin://plugin.video.smarttube'

    def test_search_url(self):
        self.assertEqual(
            'plugin://plugin.video.smarttube/search/?q=a+b',
            routes.build_url(self.BASE, 'search', q='a b'))

    def test_play_url_roundtrips(self):
        url = routes.build_url(self.BASE, 'play', video_id='dQw4w9WgXcQ')
        path, _, query = url.partition('?')
        route = routes.parse_route(
            path.replace('plugin://plugin.video.smarttube', ''), query)
        self.assertEqual('play', route.action)
        self.assertEqual('dQw4w9WgXcQ', route.video_id)

    def test_empty_params_are_dropped(self):
        self.assertEqual(
            'plugin://plugin.video.smarttube/search/?q=x',
            routes.build_url(self.BASE, 'search', q='x', continuation=''))


if __name__ == '__main__':
    unittest.main()
