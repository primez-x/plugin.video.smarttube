import sys
from pathlib import Path
import unittest

sys.path.insert(
    0, str(Path(__file__).parents[1] / 'resources' / 'lib'))

import routes  # noqa: E402
from urllib.parse import quote, urlencode  # noqa: E402


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


class AppSectionRouteTests(unittest.TestCase):
    """Hub and widget paths for the app sections."""

    def test_sections_and_pages(self):
        for name in ('subscriptions', 'continue', 'history', 'watch_later',
                     'channels', 'playlists', 'trending', 'recommended',
                     'import_subscriptions'):
            self.assertEqual(name, routes.parse_route('/%s/' % name).action)
        self.assertEqual(2, routes.parse_route('/subscriptions/', 'page=2').page)
        self.assertEqual(1, routes.parse_route('/history/', 'page=x').page)
        self.assertEqual(1, routes.parse_route('/history/', 'page=-4').page)
        self.assertEqual(1, routes.parse_route('/history/', 'page=%C2%B2').page)

    def test_explore_category(self):
        route = routes.parse_route('/explore/gaming/')
        self.assertEqual(('explore', 'gaming'), (route.action, route.category))
        with self.assertRaises(ValueError):
            routes.parse_route('/explore/')

    def test_search_menu_prompt_and_query(self):
        self.assertEqual('search_menu', routes.parse_route('/search/').action)
        self.assertEqual('search_menu', routes.parse_route('/search/', 'q=').action)
        self.assertEqual('search_prompt', routes.parse_route('/search/new/').action)
        self.assertEqual('search', routes.parse_route('/search/', 'q=x').action)
        self.assertEqual('search', routes.parse_route('/search/', 'continuation=t').action)

    def test_related_requires_a_video(self):
        self.assertEqual('v1', routes.parse_route('/related/', 'video_id=v1').video_id)
        with self.assertRaises(ValueError):
            routes.parse_route('/related/')

    def test_play_history_flag(self):
        self.assertTrue(routes.parse_route('/play/', 'video_id=v&history=1').history)
        self.assertFalse(routes.parse_route('/play/', 'video_id=v').history)

    def test_manage_validates_operation_list_and_item(self):
        item = '{"type": "video", "id": "v1", "title": "T"}'
        route = routes.parse_route('/manage/', urlencode(
            {'op': 'add', 'list': 'watch_later', 'item': item}))
        self.assertEqual(('manage', 'add', 'watch_later', 'v1'),
                         (route.action, route.op, route.list_name, route.item['id']))
        route = routes.parse_route('/manage/', 'op=remove&list=history&id=v1')
        self.assertEqual(('remove', 'v1'), (route.op, route.item['id']))
        self.assertEqual('clear', routes.parse_route('/manage/', 'op=clear&list=searches').op)
        for query in ('op=add&list=../x&id=v', 'op=drop&list=history&id=v',
                      'op=add&list=history', 'op=add&list=history&item=%7Bbad',
                      'op=add&list=history&item=%5B1%5D', 'op=remove&list=history',
                      'op=add&list=history&item=' + quote('{"id": 5}')):
            with self.assertRaises(ValueError, msg=query):
                routes.parse_route('/manage/', query)


if __name__ == '__main__':
    unittest.main()
