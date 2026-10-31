import json
import sys
from pathlib import Path
import unittest

sys.path.insert(
    0, str(Path(__file__).parents[1] / 'resources' / 'lib'))

import innertube  # noqa: E402


SEARCH_RESPONSE = {
    'contents': {'sectionListRenderer': {'contents': [
        {'itemSectionRenderer': {'contents': [
            {'videoRenderer': {
                'videoId': 'vid1',
                'title': {'runs': [{'text': 'First '}, {'text': 'Video'}]},
                'longBylineText': {'runs': [{'text': 'Channel One'}]},
                'lengthText': {'simpleText': '12:34'},
                'viewCountText': {'simpleText': '1,234 views'},
                'publishedTimeText': {'simpleText': '2 days ago'},
                'thumbnail': {'thumbnails': [
                    {'url': 'https://i.ytimg.com/small.jpg', 'width': 120},
                    {'url': 'https://i.ytimg.com/large.jpg', 'width': 480},
                ]},
            }},
            {'channelRenderer': {
                'channelId': 'UCone',
                'title': {'simpleText': 'Channel One'},
                'thumbnail': {'thumbnails': []},
            }},
            {'videoRenderer': {
                'videoId': 'vid1',  # Duplicate must be dropped.
                'title': {'simpleText': 'Dupe'},
                'thumbnail': {'thumbnails': []},
            }},
        ]}},
        {'continuationItemRenderer': {
            'continuationEndpoint': {
                'continuationCommand': {'token': 'NEXT'}}}},
    ]}},
}


def player_response(**overrides):
    data = {
        'playabilityStatus': {'status': 'OK'},
        'videoDetails': {
            'title': 'A Video', 'author': 'Channel One',
            'lengthSeconds': '754', 'isLiveContent': False,
        },
        'streamingData': {
            'dashManifestUrl': 'https://example.test/manifest.mpd',
            'formats': [
                {'itag': 18, 'url': 'https://example.test/360.mp4',
                 'height': 360, 'mimeType': 'video/mp4'},
                {'itag': 22, 'url': 'https://example.test/720.mp4',
                 'height': 720, 'mimeType': 'video/mp4'},
                {'itag': 137, 'signatureCipher': 's=abc&url=x',
                 'height': 1080},
            ],
        },
        'captions': {'playerCaptionsTracklistRenderer': {
            'captionTracks': [{
                'baseUrl': 'https://example.test/captions?lang=en',
                'languageCode': 'en',
                'name': {'simpleText': 'English'},
            }]}},
    }
    data.update(overrides)
    return data


class TextAndDurationTests(unittest.TestCase):
    def test_parse_text_variants(self):
        self.assertEqual('Hi', innertube.parse_text({'simpleText': 'Hi'}))
        self.assertEqual('ab', innertube.parse_text(
            {'runs': [{'text': 'a'}, {'text': 'b'}]}))
        self.assertEqual('', innertube.parse_text(None))
        self.assertEqual('', innertube.parse_text({}))

    def test_parse_duration(self):
        self.assertEqual(754, innertube.parse_duration('12:34'))
        self.assertEqual(3723, innertube.parse_duration('1:02:03'))
        self.assertEqual(0, innertube.parse_duration('LIVE'))
        self.assertEqual(0, innertube.parse_duration(''))


class ListingParserTests(unittest.TestCase):
    def test_search_response(self):
        items, continuation = innertube.parse_listing_response(
            SEARCH_RESPONSE)
        self.assertEqual('NEXT', continuation)
        self.assertEqual(2, len(items))
        video = items[0]
        self.assertEqual('video', video['type'])
        self.assertEqual('First Video', video['title'])
        self.assertEqual('Channel One', video['author'])
        self.assertEqual(754, video['duration'])
        self.assertEqual('https://i.ytimg.com/large.jpg',
                         video['thumbnail'])
        self.assertEqual('channel', items[1]['type'])

    def test_empty_response(self):
        self.assertEqual(([], ''), innertube.parse_listing_response({}))
        self.assertEqual(([], ''), innertube.parse_listing_response(None))


class PlayerParserTests(unittest.TestCase):
    def test_playable_with_dash_and_captions(self):
        info = innertube.parse_player_response(player_response())
        self.assertTrue(info['playable'])
        self.assertEqual('A Video', info['title'])
        self.assertEqual(754, info['length_seconds'])
        # Ciphered format without a direct url is ignored.
        self.assertEqual([720, 360],
                         [f['height'] for f in info['progressive']])
        self.assertEqual('en', info['captions'][0]['language'])
        url, kind = innertube.choose_stream(info)
        self.assertEqual(('https://example.test/manifest.mpd', 'dash'),
                         (url, kind))

    def test_progressive_fallback_without_manifests(self):
        data = player_response()
        data['streamingData'] = {'formats': [
            {'itag': 18, 'url': 'https://example.test/360.mp4',
             'height': 360}]}
        info = innertube.parse_player_response(data)
        self.assertEqual(('https://example.test/360.mp4', 'progressive'),
                         innertube.choose_stream(info))

    def test_live_prefers_hls(self):
        data = player_response()
        data['videoDetails']['isLiveContent'] = True
        data['streamingData']['hlsManifestUrl'] = (
            'https://example.test/live.m3u8')
        info = innertube.parse_player_response(data)
        self.assertEqual(('https://example.test/live.m3u8', 'hls'),
                         innertube.choose_stream(info))

    def test_adaptive_formats_need_a_url_and_byte_ranges(self):
        ranges = {'initRange': {'start': '0', 'end': '9'}, 'indexRange': {'start': '10', 'end': '99'}}
        data = player_response()
        data['streamingData'] = {'adaptiveFormats': [
            dict(ranges, itag=303, url='https://example.test/303', mimeType='video/webm'),
            dict(ranges, itag=315, signatureCipher='s=abc&url=x', mimeType='video/webm'),
            {'itag': 308, 'url': 'https://example.test/308', 'mimeType': 'video/webm'},
            'not a format']}
        info = innertube.parse_player_response(data)
        self.assertEqual([303], [fmt['itag'] for fmt in info['adaptive']])
        self.assertTrue(info['playable'])

    def test_unplayable(self):
        info = innertube.parse_player_response({
            'playabilityStatus': {
                'status': 'UNPLAYABLE', 'reason': 'Video unavailable'}})
        self.assertFalse(info['playable'])
        self.assertEqual('Video unavailable', info['reason'])
        self.assertEqual(('', ''), innertube.choose_stream(info))


class FakeTransport(object):
    """Records requests and replays canned player responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, url, data, headers, timeout):
        self.requests.append((url, json.loads(data.decode('utf-8')),
                              headers))
        return json.dumps(self.responses.pop(0)).encode('utf-8')


class GetPlaybackTests(unittest.TestCase):
    def test_falls_back_to_next_client(self):
        transport = FakeTransport([
            {'playabilityStatus': {'status': 'UNPLAYABLE',
                                   'reason': 'Nope'}},
            player_response(),
        ])
        info, client = innertube.get_playback('vid1', opener=transport)
        self.assertTrue(info['playable'])
        self.assertEqual('ios_testsuite', client)
        self.assertEqual(2, len(transport.requests))

    def test_adaptive_formats_win_without_a_manifest(self):
        data = player_response()
        data['streamingData'] = {'adaptiveFormats': [{
            'itag': 303, 'url': 'https://example.test/303', 'mimeType': 'video/webm',
            'initRange': {'start': '0', 'end': '9'}, 'indexRange': {'start': '10', 'end': '99'}}]}
        transport = FakeTransport([data])
        info, client = innertube.get_playback('vid1', opener=transport)
        self.assertEqual(('android_testsuite', 1), (client, len(transport.requests)))

    def test_live_video_keeps_looking_for_hls(self):
        adaptive = player_response()
        adaptive['videoDetails']['isLiveContent'] = True
        adaptive['streamingData'] = {'adaptiveFormats': [{
            'itag': 303, 'url': 'https://example.test/303', 'mimeType': 'video/webm',
            'initRange': {'start': '0', 'end': '9'}, 'indexRange': {'start': '10', 'end': '99'}}]}
        live = player_response()
        live['videoDetails']['isLiveContent'] = True
        live['streamingData'] = {'hlsManifestUrl': 'https://example.test/live.m3u8'}
        info, client = innertube.get_playback('vid1', opener=FakeTransport([adaptive, live]))
        self.assertEqual(('ios_testsuite', 'https://example.test/live.m3u8'), (client, info['hls_url']))

    def test_request_uses_testsuite_params_and_no_user_key(self):
        transport = FakeTransport([player_response()])
        innertube.get_playback('vid1', opener=transport)
        url, body, headers = transport.requests[0]
        self.assertIn('/youtubei/v1/player?', url)
        self.assertEqual('ANDROID',
                         body['context']['client']['clientName'])
        self.assertEqual('2AMB', body['params'])
        self.assertEqual('vid1', body['videoId'])
        self.assertNotIn('Authorization', headers)


if __name__ == '__main__':
    unittest.main()
