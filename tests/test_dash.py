"""Failure modes of the DASH manifest built from YouTube adaptive formats.

inputstream.adaptive seeks a WebM stream only to the start of a chunk, but
an MP4 stream to the exact sample, and the first video stream sets the time
every later stream seeks to. A manifest with WebM audio, or with audio
before video, starts audio seconds before video after every seek, and the
picture freezes until the audio catches up (2026-10-30).
"""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).parents[1] / 'resources' / 'lib'))
import dash  # noqa: E402

NS = {'d': 'urn:mpeg:dash:schema:mpd:2011'}
URL = 'https://rr2.googlevideo.com/videoplayback?id=1&itag=%d&expire=9&sig=a%%3Db'


def video(itag, codecs, height, fps=30, hdr=False, container='webm', **extra):
    fmt = {
        'itag': itag, 'url': URL % itag,
        'mimeType': 'video/%s; codecs="%s"' % (container, codecs),
        'bitrate': height * 10000 + fps, 'width': height * 16 // 9, 'height': height, 'fps': fps,
        'initRange': {'start': '0', 'end': '219'}, 'indexRange': {'start': '220', 'end': '1999'},
        'approxDurationMs': '3619776',
        'colorInfo': {'transferCharacteristics': 'COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084'
                      if hdr else 'COLOR_TRANSFER_CHARACTERISTICS_BT709'},
    }
    fmt.update(extra)
    return fmt


def audio(itag, codecs='mp4a.40.2', container='mp4', bitrate=130000, track=None, **extra):
    fmt = {
        'itag': itag, 'url': URL % itag,
        'mimeType': 'audio/%s; codecs="%s"' % (container, codecs), 'bitrate': bitrate,
        'audioSampleRate': '44100', 'audioChannels': 2,
        'initRange': {'start': '0', 'end': '631'}, 'indexRange': {'start': '632', 'end': '4999'},
        'approxDurationMs': '3619800',
    }
    if track:
        fmt['audioTrack'] = {'id': track[0], 'displayName': track[1], 'audioIsDefault': track[2]}
    fmt.update(extra)
    return fmt


# The adaptive formats of a 4K60 HDR video (LXb3EKWsInQ), reduced to one of each kind.
FOUR_K = [
    video(337, 'vp09.02.51.10.01.09.16.09.00', 2160, 60, hdr=True),
    video(315, 'vp09.00.51.08', 2160, 60),
    video(303, 'vp09.00.41.08', 1080, 60),
    video(244, 'vp09.00.30.08', 480, 30),
    video(701, 'av01.0.13M.10.0.110.09.16.09.0', 2160, 60, hdr=True, container='mp4'),
    video(299, 'avc1.64002a', 1080, 60, container='mp4'),
    audio(140), audio(139, 'mp4a.40.5', bitrate=49000),
    audio(251, 'opus', 'webm', 160000),
]


def parse(manifest):
    return ElementTree.fromstring(manifest)


def sets(root):
    return root.findall('d:Period/d:AdaptationSet', NS)


def itags(adaptation_set):
    return [int(rep.get('id')) for rep in adaptation_set.findall('d:Representation', NS)]


class ManifestTests(unittest.TestCase):
    def test_video_comes_before_audio(self):
        kinds = [s.get('contentType') for s in sets(parse(dash.manifest(FOUR_K)))]
        self.assertEqual(['video', 'audio'], kinds)

    def test_audio_is_the_best_mp4_track_only(self):
        audio_set = sets(parse(dash.manifest(FOUR_K)))[1]
        self.assertEqual([140], itags(audio_set))
        self.assertEqual('audio/mp4', audio_set.get('mimeType'))

    def test_drc_audio_is_not_used(self):
        formats = FOUR_K + [audio(140, bitrate=999999, isDrc=True)]
        rep = sets(parse(dash.manifest(formats)))[1].find('d:Representation', NS)
        self.assertNotEqual('999999', rep.get('bandwidth'))

    def test_vp9_sdr_is_used_without_hdr(self):
        video_set = sets(parse(dash.manifest(FOUR_K, hdr=False)))[0]
        self.assertEqual([315, 303], itags(video_set))

    def test_vp9_hdr_is_used_when_the_display_supports_hdr(self):
        self.assertEqual([337], itags(sets(parse(dash.manifest(FOUR_K, hdr=True)))[0]))

    def test_hdr_falls_back_to_sdr_when_the_video_has_no_hdr(self):
        formats = [f for f in FOUR_K if f['itag'] != 337]
        self.assertEqual([315, 303], itags(sets(parse(dash.manifest(formats, hdr=True)))[0]))

    def test_one_frame_rate_per_video_set(self):
        video_set = sets(parse(dash.manifest(FOUR_K)))[0]
        self.assertEqual({'60'}, set(rep.get('frameRate') for rep in video_set.findall('d:Representation', NS)))

    def test_av1_is_never_used(self):
        formats = [f for f in FOUR_K if not f['mimeType'].startswith('video/webm')]
        self.assertEqual([299], itags(sets(parse(dash.manifest(formats)))[0]))

    def test_h264_is_used_without_vp9(self):
        formats = [video(137, 'avc1.640028', 1080, container='mp4'),
                   video(136, 'avc1.4d401f', 720, container='mp4'), audio(140)]
        video_set = sets(parse(dash.manifest(formats)))[0]
        self.assertEqual(([137, 136], 'video/mp4'), (itags(video_set), video_set.get('mimeType')))

    def test_formats_without_a_url_or_byte_ranges_are_skipped(self):
        formats = [video(315, 'vp09.00.51.08', 2160, url=''),
                   video(308, 'vp09.00.50.08', 1440, indexRange=None),
                   video(303, 'vp09.00.41.08', 1080), audio(140)]
        self.assertEqual([303], itags(sets(parse(dash.manifest(formats)))[0]))

    def test_malformed_formats_are_skipped(self):
        # YouTube data is untrusted: a broken format must not stop the manifest.
        broken = [video(315, 'vp09.00.51.08', 2160, indexRange={'start': '220'}),
                  video(308, 'vp09.00.50.08', 1440, initRange={'start': 'x', 'end': '9'}),
                  dict(video(302, 'vp09.00.40.08', 720), height='720'),
                  dict(video(301, 'vp09.00.40.08', 720), fps='60'),
                  video(300, 'vp09.00.40.08', 720, approxDurationMs='long'),
                  dict(video(299, 'vp09.00.40.08', 720), itag='299'),
                  audio(141, bitrate='high'), audio(142, audioTrack='en'),
                  audio(143, audioTrack={'id': 4, 'displayName': 'English'}),
                  audio(144, audioChannels='2'), audio(145, approxDurationMs='\u00b2'),
                  audio(146, track=('en.4', 'English\x00', True)),
                  audio(147, track=('en\x01.4', 'English', True)),
                  audio(148, track=('en.4', 'English \ud800', True)),
                  audio(149, audioSampleRate='44\x00'),
                  dict(audio(150), url=URL % 150 + '\x1f'),
                  dict(audio(151), mimeType='audio/mp4; codecs="mp4a.40.2\x02"'),
                  audio(152, bitrate=999998, approxDurationMs='9' * 19),
                  audio(153, bitrate=999999, approxDurationMs='9' * 4301),
                  audio(154, bitrate=10 ** 5000), audio(155, approxDurationMs=10 ** 5000),
                  audio(156, audioChannels=-2)]
        root = parse(dash.manifest(broken + [video(303, 'vp09.00.41.08', 1080), audio(140)]))
        self.assertEqual([[303], [140]], [itags(s) for s in sets(root)])

    def test_no_manifest_without_video_or_mp4_audio(self):
        self.assertIsNone(dash.manifest([]))
        self.assertIsNone(dash.manifest([audio(140)]))
        self.assertIsNone(dash.manifest([video(303, 'vp09.00.41.08', 1080), audio(251, 'opus', 'webm')]))

    def test_urls_and_byte_ranges_survive_xml(self):
        rep = sets(parse(dash.manifest(FOUR_K)))[0].find('d:Representation', NS)
        self.assertEqual(URL % 315, rep.find('d:BaseURL', NS).text)
        base = rep.find('d:SegmentBase', NS)
        self.assertEqual(('220-1999', '0-219'),
                         (base.get('indexRange'), base.find('d:Initialization', NS).get('range')))

    def test_representation_attributes(self):
        rep = sets(parse(dash.manifest(FOUR_K)))[0].find('d:Representation', NS)
        self.assertEqual(('vp09.00.51.08', '3840', '2160', '21600060'),
                         (rep.get('codecs'), rep.get('width'), rep.get('height'), rep.get('bandwidth')))

    def test_duration_is_the_longest_stream(self):
        self.assertEqual('PT3619.800S', parse(dash.manifest(FOUR_K)).get('mediaPresentationDuration'))
        self.assertEqual('static', parse(dash.manifest(FOUR_K)).get('type'))

    def test_dubbed_audio_tracks_are_separate_sets_with_the_original_as_default(self):
        formats = [video(303, 'vp09.00.41.08', 1080),
                   audio(140, track=('de.3', 'German', False)),
                   audio(140, track=('en.4', 'English original', True)),
                   audio(139, 'mp4a.40.5', bitrate=49000, track=('en.4', 'English original', True))]
        audio_sets = sets(parse(dash.manifest(formats)))[1:]
        self.assertEqual(['en', 'de'], [s.get('lang') for s in audio_sets])
        self.assertEqual([['main'], []], [[r.get('value') for r in s.findall('d:Role', NS)]
                                          for s in audio_sets])
        # inputstream.adaptive reads the custom name and original attributes.
        self.assertEqual(['English original', 'German'], [s.get('name') for s in audio_sets])
        self.assertEqual(['true', None], [s.get('original') for s in audio_sets])
        self.assertEqual([[140], [140]], [itags(s) for s in audio_sets])

    def test_the_manifest_is_deterministic(self):
        self.assertEqual(dash.manifest(FOUR_K), dash.manifest(list(reversed(FOUR_K))))


class ManifestServerTests(unittest.TestCase):
    """inputstream.adaptive reads a manifest only over HTTP, never from a file."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        (self.directory / 'dash-abc_DEF-123.mpd').write_text('<MPD/>')
        (self.directory / 'history.json').write_text('[]')
        self.server = dash.ManifestServer(str(self.directory))
        self.addCleanup(self.server.close)

    def get(self, path):
        try:
            response = urllib.request.urlopen('http://127.0.0.1:%d%s' % (self.server.port, path), timeout=5)
            return response.status, response.headers.get('Content-Type'), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, None, b''

    def test_a_manifest_is_served_as_dash(self):
        self.assertEqual((200, 'application/dash+xml', b'<MPD/>'), self.get('/dash-abc_DEF-123.mpd'))
        self.assertEqual('http://127.0.0.1:%d/dash-abc_DEF-123.mpd' % self.server.port,
                         self.server.url('dash-abc_DEF-123.mpd'))

    def test_only_manifests_are_served(self):
        for path in ('/history.json', '/dash-abc.json', '/../history.json', '/%2e%2e/history.json',
                     '/dash-abc_DEF-123.mpd/x', '/sub/dash-abc_DEF-123.mpd', '/dash-missing.mpd', '/'):
            with self.subTest(path=path):
                self.assertEqual(404, self.get(path)[0])

    def test_the_server_listens_on_the_loopback_address_only(self):
        self.assertEqual('127.0.0.1', self.server.address)
        self.assertGreater(self.server.port, 0)

    def test_requests_are_served_in_parallel(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.get('/dash-abc_DEF-123.mpd')[0]))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual([200] * 8, results)

    def test_close_stops_the_server(self):
        port = self.server.port
        self.server.close()
        with self.assertRaises(OSError):
            urllib.request.urlopen('http://127.0.0.1:%d/dash-abc_DEF-123.mpd' % port, timeout=2)


if __name__ == '__main__':
    unittest.main()
