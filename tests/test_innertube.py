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
        # Kodi takes a duration as a C int
        # int() rejects a string of more than 4300 digits and non-ASCII digits
        for label in ('-5:00', '99999999:00', '1:-2', '1.5:00', '1e3', '9' * 4301, '1:' + '9' * 4301,
                      '\u00b2:00', '0:' * 3000 + '9' * 11):
            self.assertEqual(0, innertube.parse_duration(label), label)


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
        data['videoDetails'].update(isLiveContent=True, isLive=True)
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

    def test_malformed_collections_keep_the_valid_streams(self):
        # YouTube data is untrusted: a field of the wrong type is not available.
        data = player_response()
        data['streamingData'] = {'hlsManifestUrl': 'https://example.test/vod.m3u8',
                                 'dashManifestUrl': 42, 'formats': 42, 'adaptiveFormats': 42}
        data['captions'] = {'playerCaptionsTracklistRenderer': {'captionTracks': 42}}
        info = innertube.parse_player_response(data)
        self.assertEqual(('https://example.test/vod.m3u8', 'hls'), innertube.choose_stream(info))
        self.assertEqual(([], [], [], ''),
                         (info['adaptive'], info['progressive'], info['captions'], info['dash_url']))
        for broken in ({'playabilityStatus': 'OK'}, {'videoDetails': ['title']},
                       {'streamingData': ['hls']}, {'captions': 'en'},
                       {'captions': {'playerCaptionsTracklistRenderer': 'en'}},
                       {'videoDetails': {'title': 42, 'author': ['a'], 'channelId': {}}}):
            info = innertube.parse_player_response(dict(player_response(), **broken))
            self.assertIsInstance(info['title'], str)
            self.assertIsInstance(info['author'], str)
            self.assertIsInstance(info['channel_id'], str)

    def test_duration_is_whole_seconds_that_kodi_can_take(self):
        # JSON 1e309 is an infinite float; Kodi takes the duration as a C int.
        for value, seconds in (('754', 754), (754, 754), (json.loads('1e309'), 0), (-5, 0),
                               ('12.5', 0), (True, 0), ('9' * 20, 0), (2 ** 31, 0), ([], 0)):
            data = player_response()
            data['videoDetails']['lengthSeconds'] = value
            self.assertEqual(seconds, innertube.parse_player_response(data)['length_seconds'], value)

    def test_a_recorded_live_video_is_not_live(self):
        # isLiveContent stays true after the broadcast ends.
        data = player_response()
        data['videoDetails'].update(isLiveContent=True, isLive=False)
        self.assertFalse(innertube.parse_player_response(data)['is_live'])
        data['videoDetails']['isLive'] = True
        self.assertTrue(innertube.parse_player_response(data)['is_live'])
        del data['videoDetails']['isLive']
        data['microformat'] = {'playerMicroformatRenderer': {
            'liveBroadcastDetails': {'isLiveNow': True}}}
        self.assertTrue(innertube.parse_player_response(data)['is_live'])

    def test_malformed_formats_and_captions_are_skipped(self):
        data = player_response()
        data['streamingData'] = {'formats': [
            {'itag': 22, 'url': 42, 'height': 720},
            {'itag': 18, 'url': 'https://example.test/360.mp4', 'height': '360'},
            {'itag': 17, 'url': 'https://example.test/144.mp4', 'height': 144}]}
        data['captions'] = {'playerCaptionsTracklistRenderer': {'captionTracks': [
            {'baseUrl': 42, 'languageCode': 'de'},
            {'baseUrl': 'https://example.test/en', 'languageCode': 7, 'name': {'simpleText': 9}},
            {'baseUrl': 'https://example.test/fr', 'name': {'runs': [{'text': 3}, {'text': 'Fr'}]}},
            {'baseUrl': 'https://example.test/es', 'name': {'accessibility': 'es'}}]}}
        info = innertube.parse_player_response(data)
        self.assertEqual([('https://example.test/144.mp4', 144), ('https://example.test/360.mp4', 0)],
                         [(f['url'], f['height']) for f in info['progressive']])
        self.assertEqual([('', '', 'https://example.test/en'), ('', 'Fr', 'https://example.test/fr'),
                          ('', '', 'https://example.test/es')],
                         [(t['language'], t['name'], t['url']) for t in info['captions']])

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


class PlayerResponsesTests(unittest.TestCase):
    def test_every_client_answers_in_order(self):
        transport = FakeTransport([
            {'playabilityStatus': {'status': 'UNPLAYABLE', 'reason': 'Nope'}},
            player_response(), player_response()])
        responses = list(innertube.player_responses('vid1', opener=transport))
        self.assertEqual(['android_testsuite', 'ios_testsuite', 'android_vr'],
                         [client for _, client in responses])
        self.assertEqual([False, True, True], [info['playable'] for info, _ in responses])

    def test_responses_are_requested_only_when_needed(self):
        transport = FakeTransport([player_response()])
        next(innertube.player_responses('vid1', opener=transport))
        self.assertEqual(1, len(transport.requests))

    def test_a_failed_client_is_skipped(self):
        def transport(url, data, headers, timeout):
            if json.loads(data.decode('utf-8'))['context']['client']['clientName'] == 'ANDROID':
                raise OSError('offline')
            return json.dumps(player_response()).encode('utf-8')
        self.assertEqual(['ios_testsuite', 'android_vr'], [
            client for _, client in innertube.player_responses('vid1', opener=transport)])

    def test_no_answer_is_an_error(self):
        def transport(url, data, headers, timeout):
            raise OSError('offline')
        with self.assertRaises(innertube.InnertubeError):
            list(innertube.player_responses('vid1', opener=transport))

    def test_request_uses_testsuite_params_and_no_user_key(self):
        transport = FakeTransport([player_response()])
        next(innertube.player_responses('vid1', opener=transport))
        url, body, headers = transport.requests[0]
        self.assertIn('/youtubei/v1/player?', url)
        self.assertEqual('ANDROID',
                         body['context']['client']['clientName'])
        self.assertEqual('2AMB', body['params'])
        self.assertEqual('vid1', body['videoId'])
        self.assertNotIn('Authorization', headers)


if __name__ == '__main__':
    unittest.main()
