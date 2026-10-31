# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - minimal InnerTube client.

    No user API key and no Google account are required. Listings use the
    public WEB InnerTube client; playback tries the same no-PO-token player
    clients that plugin.video.youtube defaults to (testsuite-params and VR
    clients), which return directly playable stream URLs or manifests.
    Subscription uploads come from the public channel RSS feeds.

    SPDX-License-Identifier: GPL-2.0-only
"""

from concurrent.futures import ThreadPoolExecutor
import json
import re
import unicodedata
import urllib.error
import urllib.request
from xml.etree import ElementTree


BASE_URL = 'https://www.youtube.com'
V1_URL = BASE_URL + '/youtubei/v1/{endpoint}?key={key}&prettyPrint=false'
FEED_URL = BASE_URL + '/feeds/videos.xml?channel_id={channel_id}'

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
    'web_remix': {
        'key': _API_KEYS['web'],
        'client': {
            'clientName': 'WEB_REMIX',
            'clientVersion': '1.20250922.03.00',
        },
        'headers': {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/140.0.0.0 Safari/537.36'),
            'X-YouTube-Client-Name': '67',
            'X-YouTube-Client-Version': '1.20250922.03.00',
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
# Followed channels and per-request channel lists share one limit.
MAX_CHANNELS = 200
_WORKERS = 16

# YouTube's signed-out category pages. YouTube retired the general
# Trending page in July 2025; trending() reads YouTube Charts instead.
EXPLORE = {
    'music': 'UC-9-kyTW8ZkZNDHQJ6FgpwQ',
    'gaming': 'UCOpNcN46UbXVtpKMrmU4Abg',
    'news': 'UCYfdidRxbB8Qhf0Nx7ioOYw',
    'sports': 'UCEgdi0XIXXZ-qJOFPf4JSKw',
    'live': 'UC4R8DWoMoI7CAwX8_LjQHig',
    'learning': 'UCtFRv9O2AHqOZjjynzrv-xg',
    'fashion': 'UCrpQ4p1Ql_hG8rKXIKM1MOQ',
}


class InnertubeError(Exception):
    pass


def _default_opener(url, data, headers, timeout):
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method='POST')
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _default_get(url, timeout=10):
    request = urllib.request.Request(url, headers={
        'User-Agent': CLIENTS['web']['headers']['User-Agent']})
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


def _lockup_video_item(model):
    """Normalize current channel cards through the shared video parser."""
    if model.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
        return None
    metadata = (model.get('metadata') or {}).get('lockupMetadataViewModel') or {}
    thumbnail = (model.get('contentImage') or {}).get('thumbnailViewModel') or {}
    badges = [value for key, value in _walk(thumbnail.get('overlays') or [])
              if key == 'thumbnailBadgeViewModel']
    parts = [part for row in ((metadata.get('metadata') or {})
             .get('contentMetadataViewModel') or {}).get('metadataRows', [])
             for part in row.get('metadataParts', [])]
    byline = next(({'runs': [{'text': (part.get('text') or {}).get('content', ''),
                             'navigationEndpoint': {'browseEndpoint': endpoint}}]}
                   for part in parts for key, endpoint in _walk(part)
                   if key == 'browseEndpoint' and endpoint.get('browseId', '').startswith('UC')), {})
    duration = next((badge.get('text', '') for badge in badges
                     if badge.get('badgeStyle') == 'THUMBNAIL_OVERLAY_BADGE_STYLE_DEFAULT'), '')
    return _video_item({
        'videoId': model.get('contentId'),
        'title': {'simpleText': (metadata.get('title') or {}).get('content', '')},
        'thumbnail': {'thumbnails': (thumbnail.get('image') or {}).get('sources', [])},
        'shortBylineText': byline,
        'lengthText': {'simpleText': duration},
        'viewCountText': {'simpleText': ' · '.join(
            (part.get('text') or {}).get('content', '') for part in parts)},
        'thumbnailOverlays': [{'thumbnailOverlayTimeStatusRenderer': {'style': 'LIVE'}}]
            if any(badge.get('badgeStyle') == 'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE'
                   for badge in badges) else [],
    })


def _video_card_item(renderer):
    """Category pages (Gaming) use cards with byline and metadata text."""
    return _video_item(dict(renderer,
                            shortBylineText=renderer.get('bylineText') or {},
                            viewCountText=renderer.get('metadataText') or {}))


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
    'lockupViewModel': _lockup_video_item,
    'videoRenderer': _video_item,
    'videoCardRenderer': _video_card_item,
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
        'hls_url': '', 'dash_url': '', 'adaptive': [], 'progressive': [],
        'captions': [],
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
    info['channel_id'] = details.get('channelId') or ''
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
    # Separate audio and video files; dash.manifest lists them in one MPD.
    info['adaptive'] = [
        fmt for fmt in streaming.get('adaptiveFormats') or []
        if isinstance(fmt, dict) and fmt.get('url')
        and fmt.get('initRange') and fmt.get('indexRange')]
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
    info['playable'] = bool(info['hls_url'] or info['dash_url']
                            or info['adaptive'] or info['progressive'])
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
                 clients=PLAYER_CLIENT_ORDER, adaptive=True):
    """Try each player client and return (info, client_name).

    A response with a DASH or HLS manifest wins immediately, and so does a
    response with adaptive formats (any video except a live one) unless
    adaptive is False; otherwise the first playable response is kept as
    fallback while the remaining clients are tried.
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
        if (info['dash_url'] or info['hls_url']
                or (adaptive and info['adaptive'] and not info['is_live'])):
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
    """Validate up to MAX_CHANNELS unique public channel IDs from a list or text."""
    values = re.split(r'[,\s]+', value.strip()) if isinstance(value, str) else value
    result = []
    for channel_id in values:
        if not channel_id:
            continue
        if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', channel_id):
            raise ValueError('Use public YouTube channel IDs (UC plus 22 characters)')
        if channel_id not in result:
            result.append(channel_id)
    if len(result) > MAX_CHANNELS:
        raise ValueError('Use up to %d channels' % MAX_CHANNELS)
    return result


def _parallel(function, keys):
    """Run function per key; return ({key: result}, [failed keys]) in key order."""
    def run(key):
        try:
            return True, function(key)
        except (InnertubeError, OSError, ValueError):
            return False, None
    if not keys:
        return {}, []
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(keys))) as pool:
        outcomes = list(pool.map(run, keys))
    results = dict((key, value) for key, (ok, value) in zip(keys, outcomes) if ok)
    return results, [key for key, (ok, _) in zip(keys, outcomes) if not ok]


def channel_live(channel_id, hl='en', gl='US', opener=None):
    """Return the channel's current stream, or None; read at most three pages."""
    continuation = ''
    seen = set()
    for _ in range(3):
        page, token = browse(
            channel_id, params=CHANNEL_STREAMS_PARAMS,
            continuation=continuation, hl=hl, gl=gl, opener=opener)
        current = sorted((item for item in page
                          if item['type'] == 'video' and item.get('is_live')),
                         key=lambda item: item['id'])
        if current:
            return dict(current[0], channel_id=channel_id)
        if not token or token in seen:
            return None
        seen.add(token)
        continuation = token
    return None


def live_now(channels, hl='en', gl='US', opener=None, lookup=None):
    """Return one current stream per channel plus IDs whose lookup failed."""
    lookup = lookup or (lambda channel_id: channel_live(
        channel_id, hl=hl, gl=gl, opener=opener))
    results, failures = _parallel(lookup, channel_ids(channels))
    items = [dict(item, channel_id=channel_id)
             for channel_id, item in results.items() if item]
    return sorted(items, key=lambda item: (
        item.get('author', '').casefold(), item['channel_id'])), failures


_ATOM = '{http://www.w3.org/2005/Atom}'
_YT = '{http://www.youtube.com/xml/schemas/2015}'
_MEDIA = '{http://search.yahoo.com/mrss/}'


def parse_channel_feed(raw):
    """Parse a channel RSS feed into video items; Shorts are left out."""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise InnertubeError('Invalid channel feed: %s' % exc)
    items = []
    for entry in root.findall(_ATOM + 'entry'):
        video_id = entry.findtext(_YT + 'videoId') or ''
        link = entry.find(_ATOM + 'link')
        if not video_id or (link is not None and '/shorts/' in (link.get('href') or '')):
            continue
        thumbnail = entry.find(_MEDIA + 'group/' + _MEDIA + 'thumbnail')
        statistics = entry.find(_MEDIA + 'group/' + _MEDIA + 'community/'
                                + _MEDIA + 'statistics')
        views = statistics.get('views') if statistics is not None else ''
        date = entry.findtext(_ATOM + 'published') or ''
        items.append({
            'type': 'video',
            'id': video_id,
            'title': entry.findtext(_ATOM + 'title') or '',
            'author': entry.findtext(_ATOM + 'author/' + _ATOM + 'name') or '',
            'duration': 0,
            'views': '{:,} views'.format(int(views)) if (views or '').isdigit() else '',
            'published': date[:10],
            'date': date,
            'thumbnail': thumbnail.get('url') if thumbnail is not None else '',
            'is_live': False,
            'channel_id': entry.findtext(_YT + 'channelId') or '',
        })
    return items


def channel_feed(channel_id, opener=None):
    """Return the latest uploads of one public channel."""
    channel_id, = channel_ids([channel_id])
    return parse_channel_feed((opener or _default_get)(
        FEED_URL.format(channel_id=channel_id)))


def subscriptions(channels, fetch=channel_feed):
    """Merge the uploads of every channel, newest first, plus failed IDs."""
    results, failures = _parallel(fetch, channel_ids(channels))
    items = [item for uploads in results.values() for item in uploads]
    items.sort(key=lambda item: item['id'])
    items.sort(key=lambda item: item.get('date', ''), reverse=True)
    return items, failures


def parse_trending_chart(data):
    """Return the browse ID of the regional 'Trending' chart in YouTube Charts."""
    for key, renderer in _walk(data):
        if (key == 'musicTwoRowItemRenderer'
                and parse_text(renderer.get('title') or {}).startswith('Trending')):
            browse_id = ((renderer.get('navigationEndpoint') or {})
                         .get('browseEndpoint') or {}).get('browseId')
            if browse_id:
                return browse_id
    raise InnertubeError('YouTube Charts has no trending list')


def trending_chart(hl='en', gl='US', opener=None):
    # Chart titles follow hl; the chart itself follows gl. Match English titles.
    return parse_trending_chart(innertube_post(
        'browse', 'web_remix', {'browseId': 'FEmusic_charts'},
        hl='en', gl=gl, opener=opener))


def trending(hl='en', gl='US', opener=None, chart=None):
    """List the current YouTube Charts trending videos for the region."""
    return browse(chart or trending_chart(hl=hl, gl=gl, opener=opener),
                  hl=hl, gl=gl, opener=opener)


def explore(category, hl='en', gl='US', opener=None):
    if category not in EXPLORE:
        raise ValueError('Unknown category: %s' % category)
    return browse(EXPLORE[category], hl=hl, gl=gl, opener=opener)


def related(video_id, hl='en', gl='US', opener=None):
    """Return the videos YouTube suggests next to a video."""
    items, _ = parse_listing_response(innertube_post(
        'next', LISTING_CLIENT, {'videoId': video_id},
        hl=hl, gl=gl, opener=opener))
    return [item for item in items if item['id'] != video_id]


def channel_metadata(channel_id, hl='en', gl='US', opener=None):
    """Return the channel's name and largest avatar."""
    data = innertube_post('browse', LISTING_CLIENT, {'browseId': channel_id},
                          hl=hl, gl=gl, opener=opener)
    metadata = (data.get('metadata') or {}).get('channelMetadataRenderer') or {}
    if not metadata.get('title'):
        raise InnertubeError('No metadata for channel %s' % channel_id)
    return {'id': channel_id, 'title': metadata['title'],
            'thumbnail': _thumbnail_url({'thumbnail': metadata.get('avatar') or {}})}
