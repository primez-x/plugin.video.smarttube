"""Failure modes of the watch history in the background service, with a scripted player."""
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
import library  # noqa: E402

STREAM = 'https://example.test/manifest.mpd'


class ServiceHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = tmp.name
        self.store = library.Store(self.profile)
        self.properties = {'SmartTube.VideoId': 'v1', 'SmartTube.StreamUrl': STREAM,
                           'SmartTube.Item': json.dumps({'type': 'video', 'id': 'v1', 'title': 'One',
                                                         'duration': 3000})}

    def run_service(self, ticks, on_tick=None, break_store=False):
        """ticks: (playing file, position or None) per loop pass of one second."""
        state = {'tick': -1}
        def current():
            return ticks[state['tick']] if 0 <= state['tick'] < len(ticks) else ('', None)
        player = MagicMock()
        player.isPlayingVideo.side_effect = lambda: bool(current()[0])
        player.getPlayingFile.side_effect = lambda: current()[0]
        def position():
            if current()[1] is None:
                raise RuntimeError('not playing')
            return current()[1]
        player.getTime.side_effect = position
        player.getTotalTime.side_effect = lambda: 3000 if current()[1] is not None else 0
        monitor = MagicMock()
        monitor.abortRequested.side_effect = lambda: state['tick'] >= len(ticks)
        def wait(seconds):
            if on_tick:
                on_tick(state['tick'])
            state['tick'] += 1
            return state['tick'] > len(ticks)
        monitor.waitForAbort.side_effect = wait
        state['tick'] = 0
        xbmc = MagicMock(Player=lambda: player, Monitor=lambda: monitor, LOGINFO=1, LOGWARNING=2)
        window = MagicMock()
        window.getProperty.side_effect = lambda key: self.properties.get(key, '')
        addon = MagicMock()
        addon.getAddonInfo.side_effect = lambda key: {
            'id': 'plugin.video.smarttube', 'path': str(ROOT) + '/', 'profile': self.profile}.get(key, '')
        addon.getSettingBool.return_value = False
        modules = {'xbmc': xbmc, 'xbmcgui': MagicMock(Window=lambda _: window),
                   'xbmcvfs': MagicMock(translatePath=lambda path: path),
                   'xbmcaddon': SimpleNamespace(Addon=lambda: addon)}
        clock = iter(range(0, 100000, 10))
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('smarttube_service', ROOT / 'resources/lib/service.py')
            service = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(service)
            if break_store:
                service.STORE = library.Store(str(Path(self.profile) / 'missing' / 'x'))
                Path(self.profile, 'missing').write_text('blocks the directory')
            with patch.object(service.time, 'time', side_effect=lambda: next(clock)):
                service.main()
        return service, xbmc

    def history(self):
        return {entry['id']: entry for entry in self.store.load('history')}

    def test_progress_is_saved_and_the_final_position_kept_on_stop(self):
        self.run_service([(STREAM, 100), (STREAM, 200), (STREAM, 300), (STREAM, 2950), ('', None)])
        entry = self.history()['v1']
        self.assertEqual((2950, 3000), (entry['position'], entry['total']))

    def test_resuming_does_not_reset_the_saved_position(self):
        self.store.record_progress({'type': 'video', 'id': 'v1'}, 1200, 3000)
        self.run_service([(STREAM, None)])
        self.assertEqual(1200, self.history()['v1']['position'])

    def test_a_video_removed_during_playback_stays_removed(self):
        def remove(tick):
            if tick == 1:
                self.store.remove('history', 'v1')
        self.run_service([(STREAM, 100), (STREAM, 200), (STREAM, 300), ('', None)], on_tick=remove)
        self.assertEqual({}, self.history())

    def test_other_files_and_mismatched_items_are_not_recorded(self):
        self.run_service([('smb://server/movie.mkv', 100), ('', None)])
        self.properties['SmartTube.Item'] = json.dumps({'type': 'video', 'id': 'other'})
        self.run_service([(STREAM, 100), ('', None)])
        self.properties['SmartTube.Item'] = ''
        self.run_service([(STREAM, 100), ('', None)])
        self.assertEqual({}, self.history())

    def test_an_unwritable_profile_keeps_the_service_running(self):
        service, xbmc = self.run_service([(STREAM, 100), (STREAM, 200), ('', None)], break_store=True)
        self.assertTrue(any('not saved' in str(call.args[0]) for call in xbmc.log.call_args_list))


if __name__ == '__main__':
    unittest.main()
