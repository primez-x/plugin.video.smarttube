# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - minimal InnerTube client.

    No user API key and no Google account are required. Listings use the
    public WEB InnerTube client; playback tries the same no-PO-token player
    clients that plugin.video.youtube defaults to (testsuite-params and VR
    clients), which return directly playable stream URLs or manifests.

    SPDX-License-Identifier: GPL-2.0-only
"""

import json
import re
import unicodedata
import urllib.error
import urllib.request


BASE_URL = 'https://www.youtube.com'
V1_URL = BASE_URL + '/youtubei/v1/{endpoint}?key={key}&prettyPrint=false'

# Public InnerTube client keys (shipped in YouTube's own clients; these are
# not user credentials). Client versions need periodic bumps, as upstream.
_API_KEYS = {
    'android': 'AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w',
    'ios': 'AIzaSyB-63vPrdThhKuerbB2N_l7Kwwcxj6yUAc',
    'web': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
    'youtube_tv': 'AIzaSyDCU8hByM-4DrUqRUYnGn-3llEO78bcxq8',
}

_TESTSUITE_PARAMS = '2AMB'

CLIENTS = {
    'web': {
        'key': _API_KEYS['web'],
        'client': {
            'clientName': 'WEB',
            'clientVersion': '2.20250925.01.00',
        },
        'headers': {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/140.0.0.0 Safari/537.36'),
            'X-YouTube-Client-Name': '1',
            'X-YouTube-Client-Version': '2.20250925.01.00',
        },
    },
    'android_testsuite': {
        'key': _API_KEYS['android'],
        'client': {
            'clientName': 'ANDROID',
            'clientVersion': '20.10.38',
            'androidSdkVersion': 32,
            'osName': 'Android',
            'osVersion': '15',
            'platform': 'MOBILE',
        },
        'params': _TESTSUITE_PARAMS,
        'headers': {
            'User-Agent': 'com.google.android.youtube/20.10.38 (Linux; U; Android 15) gzip',
            'X-YouTube-Client-Name': '3',
            'X-YouTube-Client-Version': '20.10.38',
        },
    },
    'ios_testsuite': {
        'key': _API_KEYS['ios'],
        'client': {
            'clientName': 'IOS',
            'clientVersion': '20.20.7',
            'deviceMake': 'Apple',
            'deviceModel': 'iPhone16,2',
            'osName': 'iOS',
            'osVersion': '18.5.0.22F76',
            'platform': 'MOBILE',
        },
        'params': _TESTSUITE_PARAMS,
        'headers': {
            'User-Agent': ('com.google.ios.youtube/20.20.7 '
                           '(iPhone16,2; U; CPU iOS 18_5_0 like Mac OS X)'),
            'X-YouTube-Client-Name': '5',
            'X-YouTube-Client-Version': '20.20.7',
        },
    },
    'android_vr': {
        'key': _API_KEYS['android'],
        'client': {
            'clientName': 'ANDROID_VR',
            'clientVersion': '1.65.10',
            'androidSdkVersion': 34,
            'deviceMake': 'Oculus',
            'deviceModel': 'Quest 3',
            'osName': 'Android',
            'osVersion': '14',
        },
        'headers': {
            'User-Agent': ('com.google.android.apps.youtube.vr.oculus/1.65.10 '
                           '(Linux; U; Android 14; eureka-user '
                           'Build/UP1A.231005.007.A1) gzip'),
            'X-YouTube-Client-Name': '28',
            'X-YouTube-Client-Version': '1.65.10',
        },
    },
}

# First playable answer wins; order mirrors plugin.video.youtube defaults
# for signed-out playback (testsuite clients, then VR).
PLAYER_CLIENT_ORDER = ('android_testsuite', 'ios_testsuite', 'android_vr')
LISTING_CLIENT = 'web'
CHANNEL_STREAMS_PARAMS = 'EgdzdHJlYW1z8gYECgJ6AA%3D%3D'


class InnertubeError(Exception):
    pass


def _default_opener(url, data, headers, timeout):
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def innertube_post(endpoint, client_name, payload=None, hl='en', gl='US',
                   visitor_data=None, opener=None, timeout=15):
    """POST to youtubei/v1/<endpoint> and return the decoded JSON dict."""
    try:
        config = CLIENTS[client_name]
    except KeyError:
        raise InnertubeError('Unknown client: %s' % client_name)
    client = dict(config['client'])
    client['hl'] = hl
    client['gl'] = gl
    if visitor_data:
        client['visitorData'] = visitor_data
    body = {'context': {'client': client}}
    if config.get('params'):
        body['params'] = config['params']
    if payload:
        body.update(payload)
    url = V1_URL.format(endpoint=endpoint, key=config['key'])
    headers = {'Content-Type': 'application/json'}
    headers.update(config.get('headers') or {})
    if visitor_data:
        headers['X-Goog-Visitor-Id'] = visitor_data
    raw = (opener or _default_opener)(
        url, json.dumps(body).encode('utf-8'), headers, timeout)
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InnertubeError('Invalid %s response: %s' % (endpoint, exc))


def parse_text(node):
    """Return plain text from an InnerTube simpleText/runs node."""
    if not isinstance(node, dict):
        return ''
    if node.get('simpleText'):
        return node['simpleText']
    runs = node.get('runs')
    if isinstance(runs, list):
        return ''.join(run.get('text', '') for run in runs
                       if isinstance(run, dict))
    label = ((node.get('accessibility') or {})
             .get('accessibilityData') or {}).get('label')
    return label or ''


def parse_duration(text):
    """Convert '1:02:03' / '12:34' labels to seconds; 0 when unknown/live."""
    if not text:
        return 0
    parts = str(text).strip().split(':')
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    except ValueError:
        return 0


def _thumbnail_url(renderer):
    thumbs = ((renderer.get('thumbnail') or {}).get('thumbnails')) or []
    best = ''
    best_width = -1
    for thumb in thumbs:
        if not isinstance(thumb, dict):
            continue
        width = thumb.get('width') or 0
        if width >= best_width and thumb.get('url'):
            best, best_width = thumb['url'], width
    if best.startswith('//'):
        best = 'https:' + best
    return best


def _walk(obj):
    """Yield every (key, dict) pair in a nested InnerTube response."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict):
                yield key, value
            yield from _walk(value)
    elif isinstance(obj, list):
        for entry in obj:
            yield from _walk(entry)


def _video_item(renderer):
    video_id = renderer.get('videoId')
    if not video_id:
        return None
    badges = renderer.get('badges') or []
    is_live = any(
        ((badge.get('metadataBadgeRenderer') or {}).get('style') or '')
        in ('BADGE_STYLE_TYPE_LIVE_NOW', 'BADGE_STYLE_TYPE_LIVE')
        for badge in badges if isinstance(badge, dict))
    overlays = renderer.get('thumbnailOverlays') or []
    is_live = is_live or any(
        (overlay.get('thumbnailOverlayTimeStatusRenderer') or {}).get('style') == 'LIVE'
        for overlay in overlays if isinstance(overlay, dict))
    is_upcoming = bool(renderer.get('isUpcoming') or renderer.get('upcomingEventData'))
    byline = (renderer.get('ownerText') or renderer.get('longBylineText')
              or renderer.get('shortBylineText') or {})
    channel_id = next((
        ((run.get('navigationEndpoint') or {}).get('browseEndpoint') or {}).get('browseId')
        for run in byline.get('runs', [])
        if ((run.get('navigationEndpoint') or {}).get('browseEndpoint') or {}).get('browseId')
    ), '')
    verified = any(
        ((badge.get('metadataBadgeRenderer') or {}).get('style') or '')
        in ('BADGE_STYLE_TYPE_VERIFIED', 'BADGE_STYLE_TYPE_VERIFIED_ARTIST')
        for badge in renderer.get('ownerBadges') or [] if isinstance(badge, dict))
    return {
        'type': 'video',
        'id': video_id,
        'title': parse_text(renderer.get('title') or {}),
        'author': parse_text(
            renderer.get('ownerText') or renderer.get('longBylineText')
            or renderer.get('shortBylineText') or {}),
        'duration': parse_duration(
            parse_text(renderer.get('lengthText') or {})),
        'views': parse_text(renderer.get('viewCountText') or {}),
        'published': parse_text(renderer.get('publishedTimeText') or {}),
        'thumbnail': _thumbnail_url(renderer),
        'is_live': is_live and not is_upcoming,
        'is_upcoming': is_upcoming,
        'channel_id': channel_id,
        'author_verified': verified,
    }


def _channel_item(renderer):
    channel_id = renderer.get('channelId')
    if not channel_id:
        endpoint = ((renderer.get('navigationEndpoint') or {})
                    .get('browseEndpoint') or {})
        channel_id = endpoint.get('browseId')
    if not channel_id:
        return None
    return {
        'type': 'channel',
        'id': channel_id,
        'title': parse_text(renderer.get('title') or {}),
        'author': '',
        'duration': 0,
        'views': parse_text(renderer.get('subscriberCountText') or {}),
        'published': '',
        'thumbnail': _thumbnail_url(renderer),
        'is_live': False,
    }


def _playlist_item(renderer):
    playlist_id = renderer.get('playlistId')
    if not playlist_id:
        return None
    return {
        'type': 'playlist',
        'id': playlist_id,
        'title': parse_text(renderer.get('title') or {}),
        'author': parse_text(
            renderer.get('longBylineText')
            or renderer.get('shortBylineText') or {}),
        'duration': 0,
        'views': parse_text(renderer.get('videoCountText') or {}),
        'published': '',
        'thumbnail': _thumbnail_url(renderer),
        'is_live': False,
    }


_RENDERER_PARSERS = {
    'videoRenderer': _video_item,
    'compactVideoRenderer': _video_item,
    'gridVideoRenderer': _video_item,
    'playlistVideoRenderer': _video_item,
    'channelRenderer': _channel_item,
    'compactChannelRenderer': _channel_item,
    'playlistRenderer': _playlist_item,
    'gridPlaylistRenderer': _playlist_item,
    'compactPlaylistRenderer': _playlist_item,
}


def parse_listing_response(data):
    """Parse search/browse/next JSON into (items, continuation token)."""
    items = []
    seen = set()
    continuation = ''
    if not isinstance(data, dict):
        return items, continuation
    for key, value in _walk(data):
        parser = _RENDERER_PARSERS.get(key)
        if parser is not None:
            item = parser(value)
            if item and item['id'] and item['id'] not in seen:
                seen.add(item['id'])
                items.append(item)
        elif key == 'continuationCommand':
            token = value.get('token')
            if token:
                continuation = token
        elif key == 'nextContinuationData':
            token = value.get('continuation')
            if token:
                continuation = token
    return items, continuation


def parse_player_response(data):
    """Parse a player response into playback info (no network, testable)."""
    info = {
        'playable': False, 'reason': '', 'title': '', 'author': '',
        'length_seconds': 0, 'is_live': False,
        'hls_url': '', 'dash_url': '', 'progressive': [], 'captions': [],
    }
    if not isinstance(data, dict):
        info['reason'] = 'Empty player response'
        return info
    status = data.get('playabilityStatus') or {}
    details = data.get('videoDetails') or {}
    info['title'] = details.get('title') or ''
    info['author'] = details.get('author') or ''
    try:
        info['length_seconds'] = int(details.get('lengthSeconds') or 0)
    except (TypeError, ValueError):
        info['length_seconds'] = 0
    info['is_live'] = bool(details.get('isLiveContent'))
    if status.get('status') != 'OK':
        info['reason'] = (status.get('reason')
                          or status.get('status') or 'Not playable')
        return info
    streaming = data.get('streamingData') or {}
    info['hls_url'] = streaming.get('hlsManifestUrl') or ''
    info['dash_url'] = streaming.get('dashManifestUrl') or ''
    for fmt in streaming.get('formats') or []:
        # Ciphered formats carry signatureCipher instead of url; the player
        # clients above are chosen because they return direct urls.
        if isinstance(fmt, dict) and fmt.get('url'):
            info['progressive'].append({
                'itag': fmt.get('itag'), 'url': fmt['url'],
                'height': fmt.get('height') or 0,
                'mime': fmt.get('mimeType') or '',
            })
    info['progressive'].sort(key=lambda f: f['height'], reverse=True)
    tracks = (((data.get('captions') or {})
               .get('playerCaptionsTracklistRenderer') or {})
              .get('captionTracks')) or []
    for track in tracks:
        if isinstance(track, dict) and track.get('baseUrl'):
            info['captions'].append({
                'language': track.get('languageCode') or '',
                'name': parse_text(track.get('name') or {}),
                'url': track['baseUrl'],
            })
    info['playable'] = bool(
        info['hls_url'] or info['dash_url'] or info['progressive'])
    if not info['playable']:
        info['reason'] = 'No playable streams'
    return info


def choose_stream(info):
    """Return (url, kind) with kind 'hls', 'dash', 'progressive' or ''."""
    if info.get('is_live') and info.get('hls_url'):
        return info['hls_url'], 'hls'
    if info.get('dash_url'):
        return info['dash_url'], 'dash'
    if info.get('hls_url'):
        return info['hls_url'], 'hls'
    progressive = info.get('progressive') or []
    if progressive:
        return progressive[0]['url'], 'progressive'
    return '', ''


def search(query, continuation='', hl='en', gl='US', opener=None):
    payload = {'continuation': continuation} if continuation else {
        'query': query}
    data = innertube_post('search', LISTING_CLIENT, payload,
                          hl=hl, gl=gl, opener=opener)
    return parse_listing_response(data)


def browse(browse_id, params='', continuation='', hl='en', gl='US',
           opener=None):
    if continuation:
        payload = {'continuation': continuation}
    else:
        payload = {'browseId': browse_id}
        if params:
            payload['params'] = params
    data = innertube_post('browse', LISTING_CLIENT, payload,
                          hl=hl, gl=gl, opener=opener)
    return parse_listing_response(data)


def get_playback(video_id, hl='en', gl='US', opener=None,
                 clients=PLAYER_CLIENT_ORDER):
    """Try each player client and return (info, client_name).

    A response with a DASH or HLS manifest (full adaptive quality) wins
    immediately; otherwise the first playable progressive response is kept
    as fallback while the remaining clients are tried for a manifest.
    """
    fallback = None
    last_info = None
    last_client = ''
    for client_name in clients:
        try:
            data = innertube_post(
                'player', client_name,
                {'videoId': video_id, 'contentCheckOk': True,
                 'racyCheckOk': True},
                hl=hl, gl=gl, opener=opener)
        except (InnertubeError, urllib.error.URLError, OSError):
            continue
        info = parse_player_response(data)
        last_info, last_client = info, client_name
        if not info['playable']:
            continue
        if info['dash_url'] or info['hls_url']:
            return info, client_name
        if fallback is None:
            fallback = (info, client_name)
    if fallback is not None:
        return fallback
    if last_info is None:
        raise InnertubeError('Player request failed for %s' % video_id)
    return last_info, last_client


def _words(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    return ' '.join(re.findall(r'[^\W_]+', ''.join(
        char for char in text if not unicodedata.combining(char))))


# Channel names are a preference signal, never proof of uploader identity.
_OFFICIAL_CHANNELS = frozenset((
    'universal pictures', 'warner bros', 'warner bros pictures',
    'sony pictures entertainment', 'paramount pictures', 'walt disney studios',
    'marvel entertainment', 'pixar', '20th century studios', 'netflix',
    'prime video', 'apple tv', 'hbo', 'max', 'a24', 'lionsgate',
    'searchlight pictures', 'focus features', 'neon', 'lucasfilm', 'star wars'))


def rank_trailers(items, title, year, media_type=''):
    """Rank title-matched trailers; reject wrong years and unofficial edit types."""
    title = _words(title)
    if not title:
        return []
    ranked = {}
    for item in items:
        if (item.get('type') != 'video' or not item.get('id')
                or item.get('is_live') or item.get('is_upcoming')):
            continue
        text = _words(item.get('title', ''))
        if (' ' + title + ' ') not in (' ' + text + ' '):
            continue
        # Exclude words in the media title before classifying the trailer label.
        label = text.replace(title, '', 1)
        if not re.search(r'\btrailer\b', label):
            continue
        if re.search(r'\b(reactions?|reviews?|fan|fanmade|concept|parody|'
                     r'breakdown|explained|edits?|mashup|recap|gameplay)\b', label):
            continue
        years = re.findall(r'\b[12][0-9]{3}\b', label)
        if years and str(year) not in years:
            continue
        author = _words(item.get('author', ''))
        score = 100 if str(year) in years else 0
        score += 60 if author in _OFFICIAL_CHANNELS else 0
        score += 20 if item.get('author_verified') else 0
        score += 40 if 'official trailer' in label else 0
        score += 10 if re.search(r'\bofficial\b', label) else 0
        score += 5 if 30 <= item.get('duration', 0) <= 360 else 0
        if media_type == 'tv':
            score += 10 if re.search(r'\b(series|season|tv)\b', label) else 0
        elif media_type == 'movie':
            score -= 30 if re.search(r'\b(series|season|tv)\b', label) else 0
        previous = ranked.get(item['id'])
        if previous is None or score > previous[0]:
            ranked[item['id']] = (score, item)
    return [entry[1] for entry in sorted(
        ranked.values(), key=lambda entry: (-entry[0], entry[1]['id']))]


def find_trailers(title, year, media_type='', hl='en', gl='US', opener=None):
    """Search one public result page and return deterministic trailer candidates."""
    query = ' '.join(part for part in (
        title, str(year), 'series' if media_type == 'tv' else media_type,
        'official trailer') if part)
    items, _ = search(query, hl=hl, gl=gl, opener=opener)
    return rank_trailers(items, title, year, media_type)


def channel_ids(value):
    """Validate up to 25 unique public channel IDs from a list or text."""
    values = re.split(r'[,\s]+', value.strip()) if isinstance(value, str) else value
    result = []
    for channel_id in values:
        if not channel_id:
            continue
        if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel_id):
            raise ValueError('Use public YouTube channel IDs (UC plus 22 characters)')
        if channel_id not in result:
            result.append(channel_id)
    if len(result) > 25:
        raise ValueError('Live now supports up to 25 channels per request')
    return result


def live_now(channels, hl='en', gl='US', opener=None):
    """Return one current stream per channel plus IDs whose browse request failed."""
    items = []
    failures = []
    for channel_id in channel_ids(channels):
        continuation = ''
        seen = set()
        try:
            for _ in range(3):
                page, token = browse(
                    channel_id, params=CHANNEL_STREAMS_PARAMS,
                    continuation=continuation, hl=hl, gl=gl, opener=opener)
                current = sorted((item for item in page
                                  if item['type'] == 'video' and item.get('is_live')),
                                 key=lambda item: item['id'])
                if current:
                    items.append(dict(current[0], channel_id=channel_id))
                    break
                if not token or token in seen:
                    break
                seen.add(token)
                continuation = token
        except (InnertubeError, OSError, ValueError):
            failures.append(channel_id)
    return sorted(items, key=lambda item: (
        item.get('author', '').casefold(), item['channel_id'])), failures
