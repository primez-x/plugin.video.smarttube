"""Exercise Kodi entry points with offline YouTube response replays."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'resources/lib'))
import innertube
from test_innertube import player_response
from test_feeds import feed

CHANNEL = 'UC' + 'a' * 22
OTHER = 'UC' + 'b' * 22


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'language': 'en', 'region': 'US'}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = Path(tmp.name)
        (self.profile / 'settings.xml').write_text(
            '<settings version="2"><setting id="followed_channels">%s</setting></settings>' % CHANNEL)
        self.addon = MagicMock()
        self.addon.getAddonInfo.side_effect = lambda key: {
            'id': 'plugin.video.smarttube', 'path': str(ROOT) + '/',
            'name': 'SmartTube', 'icon': '', 'profile': str(self.profile)}.get(key, '')
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.setSetting.side_effect = self.settings.__setitem__
        self.addon.getSettingBool.return_value = False
        self.addon.getLocalizedString.side_effect = str
        self.gui = MagicMock()
        self.gui.ListItem.side_effect = lambda *a, **kw: MagicMock()
        self.kodi = MagicMock()
        self.xbmc = MagicMock()
        self.vfs = MagicMock()
        self.vfs.translatePath.side_effect = lambda path: path
        self.modules = patch.dict(sys.modules, {
            'xbmc': self.xbmc, 'xbmcgui': self.gui, 'xbmcplugin': self.kodi,
            'xbmcvfs': self.vfs, 'xbmcaddon': SimpleNamespace(Addon=lambda: self.addon)})
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

    def test_legacy_follows_migrate_and_union_with_supplied_channels(self):
        with patch.object(innertube, 'live_now', return_value=([], [])) as live:
            self.run_route('live_now', 'channel_ids=' + OTHER + ',' + CHANNEL)
        self.assertEqual([CHANNEL, OTHER], live.call_args.args[0])
        self.assertEqual([CHANNEL], [e['id'] for e in self.plugin.STORE.load('follows')])

    def test_follow_and_unfollow_through_manage(self):
        self.run_route('manage/', 'op=remove&list=follows&id=' + CHANNEL)
        self.assertEqual([], self.plugin.STORE.load('follows'))
        item = json.dumps({'type': 'channel', 'id': OTHER, 'title': 'Other'})
        self.run_route('manage/', 'op=add&list=follows&item=' + item)
        self.assertEqual([OTHER], [e['id'] for e in self.plugin.STORE.load('follows')])
        self.run_route('manage/', 'op=add&list=follows&item=' + json.dumps({'id': '../x'}))
        self.assertEqual([OTHER], [e['id'] for e in self.plugin.STORE.load('follows')])
        self.xbmc.executebuiltin.assert_any_call('Container.Refresh')
        self.kodi.endOfDirectory.assert_not_called()

    def listed(self):
        return [call.args for call in self.kodi.addDirectoryItem.call_args_list]

    def test_home_lists_every_section(self):
        self.run_route('')
        urls = [args[1] for args in self.listed()]
        self.assertEqual(len(self.plugin.SECTIONS), len(urls))
        for path in ('subscriptions/', 'continue/', 'trending/', 'live_now/', 'explore/gaming/'):
            self.assertIn('plugin://plugin.video.smarttube/' + path, urls)
        self.assertTrue(all(folder for _, _, _, folder in self.listed()))

    def test_subscriptions_list_newest_uploads_with_history_play_urls(self):
        uploads = feed(CHANNEL, [
            ('old00000001', 'Old', 'watch?v=old00000001', '2026-10-01T00:00:00+00:00'),
            ('new00000001', 'New', 'watch?v=new00000001', '2026-10-29T00:00:00+00:00'),
            ('short000001', 'Short', 'shorts/short000001', '2026-10-30T00:00:00+00:00')])
        with patch.object(innertube, '_default_get', return_value=uploads) as get:
            self.run_route('subscriptions/')
            self.run_route('subscriptions/')
        self.assertEqual(1, get.call_count, 'the second call reads the feed cache')
        urls = [args[1] for args in self.listed()]
        self.assertEqual(['plugin://plugin.video.smarttube/play/?video_id=new00000001&history=1',
                          'plugin://plugin.video.smarttube/play/?video_id=old00000001&history=1'],
                         urls[:2])
        self.assertEqual(4, len(urls))

    def test_unreachable_subscriptions_fail_the_listing(self):
        with patch.object(innertube, '_default_get', side_effect=OSError('offline')):
            self.run_route('subscriptions/')
        self.kodi.endOfDirectory.assert_called_once_with(7, succeeded=False)

    def test_watch_later_round_trip_and_context_toggle(self):
        item = json.dumps({'type': 'video', 'id': 'saved000001', 'title': 'Saved', 'channel_id': CHANNEL})
        self.run_route('manage/', 'op=add&list=watch_later&item=' + item)
        self.run_route('watch_later/')
        (_, url, list_item, folder), = self.listed()
        self.assertEqual(('plugin://plugin.video.smarttube/play/?video_id=saved000001&history=1', False),
                         (url, folder))
        labels = [label for label, _ in list_item.addContextMenuItems.call_args.args[0]]
        self.assertEqual(['32070', '32071', '32073', '32018'], labels)

    def test_history_continue_and_resume_points(self):
        store = self.plugin.STORE
        store.record_progress({'type': 'video', 'id': 'done0000001', 'title': 'Done'}, 590, 600)
        store.record_progress({'type': 'video', 'id': 'half0000001', 'title': 'Half'}, 300, 600)
        self.run_route('continue/')
        (_, url, list_item, _), = self.listed()
        self.assertIn('half0000001', url)
        list_item.getVideoInfoTag.return_value.setResumePoint.assert_called_once_with(300, 600)
        labels = [label for label, _ in list_item.addContextMenuItems.call_args.args[0]]
        self.assertEqual(['32074', '32075'], labels[-2:])
        self.kodi.reset_mock()
        self.run_route('history/')
        self.assertEqual(2, len(self.listed()))

    def test_long_category_pages_split_locally(self):
        rows = [{'type': 'video', 'id': 'v%03d' % n, 'title': str(n)} for n in range(130)]
        with patch.object(innertube, 'explore', return_value=(rows, 'ignored')):
            self.run_route('explore/news/', 'page=2')
        urls = [args[1] for args in self.listed()]
        self.assertEqual(61, len(urls))
        self.assertIn('video_id=v060', urls[0])
        self.assertEqual('plugin://plugin.video.smarttube/explore/news/?page=3', urls[-1])

    def test_clear_needs_confirmation(self):
        self.plugin.STORE.add('searches', {'id': 'cats'})
        self.gui.Dialog.return_value.yesno.return_value = False
        self.run_route('manage/', 'op=clear&list=searches')
        self.assertEqual(1, len(self.plugin.STORE.load('searches')))
        self.gui.Dialog.return_value.yesno.return_value = True
        self.run_route('manage/', 'op=clear&list=searches')
        self.assertEqual([], self.plugin.STORE.load('searches'))

    def test_search_prompt_records_query_and_menu_lists_it(self):
        self.gui.Dialog.return_value.input.return_value = ' cats '
        self.run_route('search/new/')
        self.kodi.endOfDirectory.assert_called_once_with(7, succeeded=False)
        self.xbmc.executebuiltin.assert_called_with(
            'Container.Update(plugin://plugin.video.smarttube/search/?q=cats)')
        self.kodi.reset_mock()
        self.run_route('search/')
        urls = [args[1] for args in self.listed()]
        self.assertEqual(['plugin://plugin.video.smarttube/search/new/',
                          'plugin://plugin.video.smarttube/search/?q=cats'], urls)

    def test_widget_search_does_not_record_history(self):
        with self.replay('trailers'):
            self.run_route('search/', 'q=orbit')
        self.assertEqual([], self.plugin.STORE.load('searches'))
        self.assertTrue(self.listed())

    def test_takeout_import_adds_channels(self):
        self.gui.Dialog.return_value.browseSingle.return_value = '/media/subscriptions.csv'
        self.vfs.File.return_value.read.return_value = (
            'Channel Id,Channel Url,Channel Title\n' + CHANNEL + ',u,Known\n' + OTHER + ',u,Other\n')
        self.addon.getLocalizedString.side_effect = lambda string_id: (
            'New channels followed: %d' if string_id == 32083 else str(string_id))
        self.plugin.main(['plugin://plugin.video.smarttube/import_subscriptions/', '-1', ''])
        self.assertEqual([CHANNEL, OTHER], [e['id'] for e in self.plugin.STORE.load('follows')])
        self.gui.Dialog.return_value.notification.assert_called_once()
        self.assertEqual('New channels followed: 1',
                         self.gui.Dialog.return_value.notification.call_args.args[1])
        self.kodi.endOfDirectory.assert_not_called()

    def test_offline_live_listing_reports_failure(self):
        with patch.object(innertube, 'live_now', return_value=([], [CHANNEL])):
            self.run_route('live_now')
        self.gui.Dialog.return_value.notification.assert_called()
        self.kodi.endOfDirectory.assert_called_once_with(7, succeeded=False)

    def test_history_play_hands_the_item_to_the_service(self):
        playback = player_response()
        playback['videoDetails']['channelId'] = CHANNEL
        with patch.object(innertube, '_default_opener', return_value=json.dumps(playback).encode()):
            self.run_route('play/', 'video_id=abc&history=1')
        item = dict(call.args for call in self.gui.Window.return_value.setProperty.call_args_list)
        self.assertEqual({'type': 'video', 'id': 'abc', 'title': 'A Video', 'author': 'Channel One',
                          'channel_id': CHANNEL, 'duration': 754, 'is_live': False,
                          'thumbnail': 'https://i.ytimg.com/vi/abc/hqdefault.jpg'},
                         json.loads(item['SmartTube.Item']))

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

    def _play_adaptive(self, hdr_types='', port='41234', kodi='21.3 (21.3.0) Git:20261016-p3i', **streaming):
        import test_dash
        playback = player_response()
        playback['streamingData'] = dict({'adaptiveFormats': test_dash.FOUR_K}, **streaming)
        self.xbmc.getInfoLabel.side_effect = lambda label: {
            'System.SupportedHDRTypes': hdr_types, 'System.BuildVersion': kodi}.get(label, '')
        self.gui.Window.return_value.getProperty.side_effect = lambda key: (
            port if key == 'SmartTube.ManifestPort' else '')
        with patch.object(innertube, '_default_opener', return_value=json.dumps(playback).encode()):
            self.run_route('play/', 'video_id=abc')
        self.assertEqual((7, True), self.kodi.setResolvedUrl.call_args.args[:2])
        return self.gui.ListItem.call_args.kwargs.get('path') or self.gui.ListItem.call_args.args[0]

    def manifest(self):
        return (self.profile / 'cache' / 'dash-abc.mpd').read_text()

    def test_adaptive_formats_play_from_a_dash_manifest_served_by_the_service(self):
        url = self._play_adaptive()
        self.assertEqual('http://127.0.0.1:41234/dash-abc.mpd', url)
        self.assertIn('id="315"', self.manifest())
        self.assertNotIn('id="337"', self.manifest())
        resolved = self.kodi.setResolvedUrl.call_args.args[2]
        resolved.setProperty.assert_any_call('inputstream', 'inputstream.adaptive')
        resolved.setMimeType.assert_called_with('application/dash+xml')
        self.gui.Window.return_value.setProperty.assert_any_call('SmartTube.StreamUrl', url)

    def test_an_hdr_display_gets_the_hdr_streams_on_kodi_22(self):
        self._play_adaptive('HDR10, HLG', kodi='22.0-ALPHA2 (21.90.802) Git:20261001')
        self.assertIn('id="337"', self.manifest())

    def test_kodi_21_gets_sdr_streams_on_an_hdr_display(self):
        # Kodi 21 never reports HDR for inputstream add-on streams (fixed upstream
        # in 085c4d3), so the TV would show HDR video as SDR with wrong colours.
        self._play_adaptive('HDR10, HLG, Dolby Vision')
        self.assertIn('id="315"', self.manifest())
        self.assertNotIn('id="337"', self.manifest())

    def test_hdr_on_plays_hdr_on_kodi_21_with_hdr_support(self):
        # Firmware with the 085c4d3 backport reports HDR but still says Kodi 21.
        self.settings['hdr'] = 'on'
        self._play_adaptive('HDR10, HLG')
        self.assertIn('id="337"', self.manifest())

    def test_hdr_on_plays_sdr_on_a_display_without_hdr(self):
        self.settings['hdr'] = 'on'
        self._play_adaptive('')
        self.assertNotIn('id="337"', self.manifest())

    def test_hdr_off_plays_sdr_on_kodi_22(self):
        self.settings['hdr'] = 'off'
        self._play_adaptive('HDR10, HLG', kodi='22.0-ALPHA2 (21.90.802) Git:20261001')
        self.assertNotIn('id="337"', self.manifest())

    def test_without_the_manifest_server_playback_uses_hls(self):
        url = self._play_adaptive(port='', hlsManifestUrl='https://example.test/vod.m3u8')
        self.assertEqual('https://example.test/vod.m3u8', url)

    def test_without_dash_playback_asks_the_next_client_for_hls(self):
        # android_testsuite gives adaptive formats but no HLS manifest; without
        # the manifest server, playback must not drop to the 360p file.
        import test_dash
        android = player_response()
        android['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K,
                                    'formats': player_response()['streamingData']['formats']}
        ios = player_response()
        ios['streamingData'] = {'hlsManifestUrl': 'https://example.test/ios.m3u8'}
        clients = []
        def transport(url, data, headers, timeout):
            name = json.loads(data)['context']['client']['clientName']
            clients.append(name)
            return json.dumps(ios if name == 'IOS' else android).encode()
        self.gui.Window.return_value.getProperty.side_effect = lambda key: ''
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.run_route('play/', 'video_id=abc')
        self.assertEqual('https://example.test/ios.m3u8',
                         self.gui.ListItem.call_args.kwargs.get('path'))
        self.assertEqual(['ANDROID', 'IOS'], clients)

    def _play_from_clients(self, responses, port=''):
        """Play abc; return the path and the clients asked. Without a port, no manifest server."""
        clients = []
        def transport(url, data, headers, timeout):
            name = json.loads(data)['context']['client']['clientName']
            clients.append(name)
            return json.dumps(responses[name]).encode()
        self.gui.Window.return_value.getProperty.side_effect = lambda key: (
            port if key == 'SmartTube.ManifestPort' else '')
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.run_route('play/', 'video_id=abc')
        resolved = self.kodi.setResolvedUrl.call_args.args[1]
        return resolved and self.gui.ListItem.call_args.kwargs.get('path'), clients

    @staticmethod
    def _progressive(url):
        playback = player_response()
        playback['streamingData'] = {'formats': [
            {'itag': 22, 'url': url, 'height': 720, 'mimeType': 'video/mp4'}]}
        return playback

    def test_a_later_progressive_file_plays_when_the_first_client_has_only_adaptive_formats(self):
        import test_dash
        android = player_response()
        android['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K}
        path, clients = self._play_from_clients({
            'ANDROID': android, 'IOS': self._progressive('https://example.test/ios.mp4'),
            'ANDROID_VR': self._progressive('https://example.test/vr.mp4')})
        self.assertEqual('https://example.test/ios.mp4', path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)

    def test_each_client_is_asked_once_when_every_client_has_only_progressive_files(self):
        path, clients = self._play_from_clients({
            name: self._progressive('https://example.test/%s.mp4' % name)
            for name in ('ANDROID', 'IOS', 'ANDROID_VR')})
        self.assertEqual('https://example.test/ANDROID.mp4', path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)

    def test_dash_from_a_later_client_beats_an_earlier_hls_manifest(self):
        import test_dash
        android = player_response()
        android['streamingData'] = {'hlsManifestUrl': 'https://example.test/android.m3u8'}
        ios = player_response()
        ios['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K}
        path, clients = self._play_from_clients(
            {'ANDROID': android, 'IOS': ios, 'ANDROID_VR': android}, port='41234')
        self.assertEqual('http://127.0.0.1:41234/dash-abc.mpd', path)
        self.assertEqual(['ANDROID', 'IOS'], clients)

    def test_an_hls_manifest_beats_a_later_progressive_file(self):
        android = player_response()
        android['streamingData'] = {'hlsManifestUrl': 'https://example.test/android.m3u8'}
        path, clients = self._play_from_clients({
            'ANDROID': android, 'IOS': self._progressive('https://example.test/ios.mp4'),
            'ANDROID_VR': self._progressive('https://example.test/vr.mp4')}, port='41234')
        self.assertEqual('https://example.test/android.m3u8', path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)

    def test_a_failed_manifest_write_keeps_the_earlier_hls(self):
        import test_dash
        android = player_response()
        android['streamingData'] = {'hlsManifestUrl': 'https://example.test/android.m3u8'}
        ios = player_response()
        ios['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K}
        write_text = self.plugin.library.write_text
        def full_disk(path, text):
            if path.endswith('.mpd'):
                raise OSError('disk full')
            write_text(path, text)
        with patch.object(self.plugin.library, 'write_text', side_effect=full_disk):
            path, clients = self._play_from_clients(
                {'ANDROID': android, 'IOS': ios, 'ANDROID_VR': ios}, port='41234')
        self.assertEqual('https://example.test/android.m3u8', path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)

    def test_an_unwritable_manifest_keeps_the_earlier_hls(self):
        # An unpaired surrogate in a track name is not valid XML or UTF-8.
        import test_dash
        android = player_response()
        android['streamingData'] = {'hlsManifestUrl': 'https://example.test/android.m3u8'}
        ios = player_response()
        ios['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K[:-3] + [test_dash.audio(
            140, track=('en.4', 'English \ud800', True))]}
        path, clients = self._play_from_clients(
            {'ANDROID': android, 'IOS': ios, 'ANDROID_VR': ios}, port='41234')
        self.assertEqual('https://example.test/android.m3u8', path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)

    def test_a_later_client_restriction_is_not_the_reason(self):
        # The first client answers, but no stream can play without the manifest server.
        import test_dash
        android = player_response()
        android['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K}
        restricted = {'playabilityStatus': {'status': 'LOGIN_REQUIRED',
                                            'reason': 'Sign in to confirm your age'}}
        path, clients = self._play_from_clients(
            {'ANDROID': android, 'IOS': restricted, 'ANDROID_VR': restricted})
        self.assertFalse(path)
        self.assertEqual('No playable streams',
                         self.gui.Dialog.return_value.notification.call_args.args[1])

    def test_live_playback_asks_the_next_client_for_hls(self):
        # A live video has adaptive formats but no DASH manifest from them.
        live = player_response()
        live['videoDetails']['isLiveContent'] = True
        android = json.loads(json.dumps(live))
        android['streamingData'] = {'adaptiveFormats': [{
            'itag': 303, 'url': 'https://example.test/303', 'mimeType': 'video/webm',
            'initRange': {'start': '0', 'end': '9'}, 'indexRange': {'start': '10', 'end': '99'}}]}
        live['streamingData'] = {'hlsManifestUrl': 'https://example.test/live.m3u8'}
        path, clients = self._play_from_clients({'ANDROID': android, 'IOS': live})
        self.assertEqual('https://example.test/live.m3u8', path)
        self.assertEqual(['ANDROID', 'IOS'], clients)

    def test_an_unplayable_video_shows_the_reason(self):
        unplayable = {'playabilityStatus': {'status': 'UNPLAYABLE', 'reason': 'Video unavailable'}}
        path, clients = self._play_from_clients(
            dict.fromkeys(('ANDROID', 'IOS', 'ANDROID_VR'), unplayable))
        self.assertFalse(path)
        self.assertEqual(['ANDROID', 'IOS', 'ANDROID_VR'], clients)
        self.assertEqual('Video unavailable', self.gui.Dialog.return_value.notification.call_args.args[1])

    def test_dash_playback_asks_only_one_client(self):
        clients = []
        def transport(url, data, headers, timeout):
            clients.append(json.loads(data)['context']['client']['clientName'])
            import test_dash
            playback = player_response()
            playback['streamingData'] = {'adaptiveFormats': test_dash.FOUR_K}
            return json.dumps(playback).encode()
        self.gui.Window.return_value.getProperty.side_effect = lambda key: (
            '41234' if key == 'SmartTube.ManifestPort' else '')
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.run_route('play/', 'video_id=abc')
        self.assertEqual(['ANDROID'], clients)

    def test_adaptive_formats_without_mp4_audio_fall_back_to_hls(self):
        import test_dash
        formats = [fmt for fmt in test_dash.FOUR_K if not fmt['mimeType'].startswith('audio/mp4')]
        playback = player_response()
        playback['streamingData'] = {'adaptiveFormats': formats,
                                     'hlsManifestUrl': 'https://example.test/vod.m3u8'}
        self.gui.Window.return_value.getProperty.side_effect = lambda key: (
            '41234' if key == 'SmartTube.ManifestPort' else '')
        with patch.object(innertube, '_default_opener', return_value=json.dumps(playback).encode()):
            self.run_route('play/', 'video_id=abc')
        self.assertEqual('https://example.test/vod.m3u8',
                         self.gui.ListItem.call_args.kwargs.get('path'))
        self.assertFalse((self.profile / 'cache' / 'dash-abc.mpd').exists())

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
        self.gui.Window.return_value.setProperty.assert_any_call('SmartTube.Item', '')
        resolved = self.kodi.setResolvedUrl.call_args.args[2]
        resolved.setProperty.assert_any_call('Starlight.Source', 'YouTube')
        resolved.setProperty.assert_any_call('IsLive', 'true' if live else 'false')
        resolved.setProperty.assert_any_call('inputstream', 'inputstream.adaptive')
        resolved.setProperty.assert_any_call('inputstream.adaptive.manifest_type', 'hls' if live else 'mpd')
        self.assertTrue(requests[-1]['videoId'].startswith('record'))
        self.kodi.endOfDirectory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
