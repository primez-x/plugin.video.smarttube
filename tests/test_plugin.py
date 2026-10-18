"""Exercise Kodi entry points with offline YouTube response replays."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'resources/lib'))
import innertube
from test_innertube import player_response

CHANNEL = 'UC' + 'a' * 22


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'language': 'en', 'region': 'US', 'followed_channels': CHANNEL}
        self.addon = MagicMock()
        self.addon.getAddonInfo.side_effect = lambda key: {
            'id': 'plugin.video.smarttube', 'path': str(ROOT) + '/',
            'name': 'SmartTube', 'icon': ''}.get(key, '')
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.setSetting.side_effect = self.settings.__setitem__
        self.addon.getSettingBool.return_value = False
        self.addon.getLocalizedString.side_effect = str
        self.gui = MagicMock()
        self.gui.ListItem.side_effect = lambda *a, **kw: MagicMock()
        self.kodi = MagicMock()
        self.modules = patch.dict(sys.modules, {
            'xbmc': MagicMock(), 'xbmcgui': self.gui, 'xbmcplugin': self.kodi,
            'xbmcaddon': SimpleNamespace(Addon=lambda: self.addon)})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location('smarttube_plugin', ROOT / 'resources/lib/plugin.py')
        self.plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.plugin)

    def replay(self, name):
        data = (ROOT / 'tests/fixtures' / (name + '.json')).read_bytes()
        return patch.object(innertube, '_default_opener', return_value=data)

    def run_route(self, path, query=''):
        self.plugin.main(['plugin://plugin.video.smarttube/' + path, '7', '?' + query])

    def test_trailer_play_resolves_best_result(self):
        with self.replay('trailers'), patch.object(self.plugin, '_resolve_play') as play:
            self.run_route('trailer', 'title=Orbit&year=2026')
        play.assert_called_once_with(7, 'official001')
        self.kodi.endOfDirectory.assert_not_called()

    def test_trailer_lookup_lists_playable_art_without_playback(self):
        with self.replay('trailers'), patch.object(self.plugin, '_resolve_play') as play:
            self.run_route('trailer', 'title=Orbit&year=2026&mode=lookup')
        play.assert_not_called()
        self.assertEqual(2, self.kodi.addDirectoryItem.call_count)
        handle, url, item, folder = self.kodi.addDirectoryItem.call_args_list[0].args
        self.assertEqual((7, 'plugin://plugin.video.smarttube/play/?video_id=official001', False),
                         (handle, url, folder))
        item.setProperty.assert_any_call('Starlight.Source', 'YouTube')
        item.setProperty.assert_any_call('IsPlayable', 'true')
        self.assertEqual('https://example.test/thumb.jpg', item.setArt.call_args.args[0]['landscape'])
        self.kodi.setResolvedUrl.assert_not_called()
        self.kodi.endOfDirectory.assert_called_once_with(7)

    def test_no_trailer_and_network_error_resolve_failure(self):
        for error in (False, True):
            self.kodi.reset_mock()
            with patch.object(innertube, 'find_trailers', **(
                    {'side_effect': innertube.InnertubeError('offline')} if error else {'return_value': []})):
                self.run_route('trailer', 'title=Orbit&year=2026')
            self.assertEqual((7, False), self.kodi.setResolvedUrl.call_args.args[:2])
            self.kodi.endOfDirectory.assert_not_called()

    def test_invalid_trailer_does_not_escape_or_start_network(self):
        with patch.object(innertube, 'find_trailers') as find:
            self.run_route('trailer', 'title=Orbit&year=bad')
        find.assert_not_called()
        self.assertEqual((7, False), self.kodi.setResolvedUrl.call_args.args[:2])

    def test_live_row_rechecks_channel_on_play_and_has_live_properties(self):
        with self.replay('live'):
            self.run_route('live_now')
        self.assertEqual(1, self.kodi.addDirectoryItem.call_count)
        handle, url, item, folder = self.kodi.addDirectoryItem.call_args.args
        self.assertEqual((7, False), (handle, folder))
        self.assertEqual('plugin://plugin.video.smarttube/play/?channel_id=' + CHANNEL + '&live=1', url)
        item.setProperty.assert_any_call('Starlight.Source', 'YouTube')
        item.setProperty.assert_any_call('IsLive', 'true')
        item.setProperty.assert_any_call('Starlight.IsLive', 'true')
        self.kodi.setResolvedUrl.assert_not_called()

    def test_follow_toggle_and_imported_subscriptions_union(self):
        self.run_route('follow', 'channel_id=' + CHANNEL)
        self.assertEqual('', self.settings['followed_channels'])
        self.run_route('follow', 'channel_id=' + CHANNEL)
        self.assertEqual(CHANNEL, self.settings['followed_channels'])
        other = 'UC' + 'b' * 22
        with patch.object(innertube, 'live_now', return_value=([], [])) as live:
            self.run_route('live_now', 'channel_ids=' + other + ',' + CHANNEL)
        self.assertEqual([CHANNEL, other], live.call_args.args[0])

    def test_offline_live_listing_reports_failure(self):
        with patch.object(innertube, 'live_now', return_value=([], [CHANNEL])):
            self.run_route('live_now')
        self.gui.Dialog.return_value.notification.assert_called()
        self.kodi.endOfDirectory.assert_called_once_with(7, succeeded=False)

    def test_live_play_uses_current_response(self):
        with self.replay('live'), patch.object(self.plugin, '_resolve_play') as play:
            self.run_route('play/', 'channel_id=' + CHANNEL + '&live=1')
        play.assert_called_once_with(7, 'livevideo01')

    def test_recorded_trailer_request_reaches_resolved_stream(self):
        self._replay_complete_playback('trailer',
            'title=Orbit&year=2026', 'recorded_trailers', live=False)

    def test_recorded_live_request_reaches_resolved_stream(self):
        self._replay_complete_playback('play/',
            'channel_id=' + CHANNEL + '&live=1', 'recorded_live', live=True)

    def _replay_complete_playback(self, path, query, fixture, live):
        listing = (ROOT / 'tests/fixtures' / (fixture + '.json')).read_bytes()
        playback = player_response()
        playback['videoDetails']['isLiveContent'] = live
        if live:
            playback['streamingData']['hlsManifestUrl'] = 'https://example.test/live.m3u8'
        requests = []
        def transport(url, data, headers, timeout):
            requests.append(json.loads(data))
            return json.dumps(playback).encode() if '/player?' in url else listing
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.run_route(path, query)
        self.assertEqual((7, True), self.kodi.setResolvedUrl.call_args.args[:2])
        resolved = self.kodi.setResolvedUrl.call_args.args[2]
        resolved.setProperty.assert_any_call('Starlight.Source', 'YouTube')
        resolved.setProperty.assert_any_call('IsLive', 'true' if live else 'false')
        resolved.setProperty.assert_any_call('inputstream', 'inputstream.adaptive')
        resolved.setProperty.assert_any_call('inputstream.adaptive.manifest_type', 'hls' if live else 'mpd')
        self.assertTrue(requests[-1]['videoId'].startswith('record'))
        self.kodi.endOfDirectory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
