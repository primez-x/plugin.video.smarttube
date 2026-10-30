# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - SponsorBlock, DeArrow and Return YouTube Dislike.

    All parsers are pure functions; fetchers take an injectable opener
    (callable(url) -> bytes) so tests need no network and no Kodi.

    SPDX-License-Identifier: GPL-2.0-only
"""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request


SPONSORBLOCK_API = 'https://sponsor.ajay.app/api/skipSegments/{prefix}'
DEARROW_API = 'https://sponsor.ajay.app/api/branding?videoID={video_id}'
DEARROW_THUMBNAIL = ('https://dearrow-thumb.ajay.app/api/v1/getThumbnail'
                     '?videoID={video_id}&time={time}')
RYD_API = 'https://returnyoutubedislikeapi.com/votes?videoId={video_id}'

# Every SponsorBlock category SmartTube exposes.
ALL_CATEGORIES = (
    'sponsor', 'selfpromo', 'interaction', 'intro', 'outro', 'preview',
    'hook', 'music_offtopic', 'filler', 'poi_highlight',
)

_USER_AGENT = 'SmartTube-Kodi/0.1.0'
BRANDING_TIMEOUT = 2


def _default_get(url, timeout=10):
    request = urllib.request.Request(
        url, headers={'User-Agent': _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _get_json(url, opener=None):
    raw = (opener or _default_get)(url)
    return json.loads(raw.decode('utf-8'))


def parse_segments(data, video_id):
    """Extract sorted skip segments for video_id from a SponsorBlock
    hash-prefix response (a list of per-video objects)."""
    segments = []
    if not isinstance(data, list):
        return segments
    for entry in data:
        if not isinstance(entry, dict) or entry.get('videoID') != video_id:
            continue
        for segment in entry.get('segments') or []:
            if not isinstance(segment, dict):
                continue
            span = segment.get('segment')
            if (not isinstance(span, (list, tuple)) or len(span) != 2
                    or segment.get('actionType') not in (None, 'skip')):
                continue
            try:
                start, end = float(span[0]), float(span[1])
            except (TypeError, ValueError):
                continue
            if end > start:
                segments.append({
                    'category': segment.get('category') or '',
                    'start': start,
                    'end': end,
                    'uuid': segment.get('UUID') or '',
                })
    segments.sort(key=lambda item: item['start'])
    return segments


def fetch_segments(video_id, categories=ALL_CATEGORIES, opener=None):
    """Fetch SponsorBlock segments using the privacy hash-prefix API."""
    prefix = hashlib.sha256(video_id.encode('utf-8')).hexdigest()[:4]
    query = urllib.parse.urlencode({
        'categories': json.dumps(list(categories)),
        'actionTypes': json.dumps(['skip']),
    })
    url = SPONSORBLOCK_API.format(prefix=prefix) + '?' + query
    try:
        data = _get_json(url, opener)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # No segments known for this hash prefix.
            return []
        raise
    return parse_segments(data, video_id)


class SegmentSkips(object):
    """Decide SponsorBlock skips for one playing file.

    Each segment skips once. A seek on an adaptive stream resumes at the
    chunk start before the target, which can still lie inside the segment,
    so a segment re-arms only after playback leaves the segment.
    """

    def __init__(self, segments):
        self._segments = segments or []
        self._skipped = set()

    def check(self, position):
        """Return the segment to skip at position (seconds), else None."""
        target = None
        for index, segment in enumerate(self._segments):
            # A small tolerance past the end counts as past the segment.
            if not segment['start'] <= position < segment['end'] - 0.5:
                self._skipped.discard(index)
            elif index not in self._skipped:
                self._skipped.add(index)
                if target is None or segment['end'] > target['end']:
                    target = segment
        return target


def ends_video(segment, total_time):
    """True when segment runs to the end of a video of total_time seconds."""
    return total_time > 0 and segment['end'] >= total_time - 1.0


def parse_branding(data, video_id=''):
    """Pick a DeArrow replacement (title, thumbnail) or (None, None).

    A candidate wins when it is locked or has a non-negative vote score;
    original entries never replace anything.
    """
    if not isinstance(data, dict):
        return None, None
    title = None
    for candidate in data.get('titles') or []:
        if not isinstance(candidate, dict) or candidate.get('original'):
            continue
        if candidate.get('locked') or (candidate.get('votes') or 0) >= 0:
            title = candidate.get('title') or None
            break
    thumbnail = None
    for candidate in data.get('thumbnails') or []:
        if not isinstance(candidate, dict) or candidate.get('original'):
            continue
        if candidate.get('locked') or (candidate.get('votes') or 0) >= 0:
            # DeArrow submits a frame time; the thumbnail service renders the frame.
            timestamp = candidate.get('timestamp')
            if isinstance(timestamp, (int, float)) and video_id:
                thumbnail = DEARROW_THUMBNAIL.format(
                    video_id=urllib.parse.quote(video_id), time=timestamp)
            break
    return title, thumbnail


def fetch_branding(video_id, opener=None):
    url = DEARROW_API.format(video_id=urllib.parse.quote(video_id))
    try:
        # Titles are cosmetic: a slow answer must not hold up the listing.
        data = _get_json(url, opener or (
            lambda request_url: _default_get(request_url, timeout=BRANDING_TIMEOUT)))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # No DeArrow submissions for this video.
            return None, None
        raise
    return parse_branding(data, video_id)


def apply_dearrow(items, fetch=None):
    """Return copies of video items with DeArrow title/thumbnail applied.

    Failures for a single video leave that item unchanged.
    """
    fetch = fetch or fetch_branding

    def apply(item):
        if item.get('type') != 'video':
            return item
        try:
            title, thumbnail = fetch(item['id'])
        except Exception:  # DeArrow must never break a listing.
            return item
        updated = dict(item)
        if title:
            updated['title'] = title
        if thumbnail:
            updated['thumbnail'] = thumbnail
        return updated

    items = list(items or [])
    if not items:
        return []
    # One request per video; run them together so long pages stay fast.
    with ThreadPoolExecutor(max_workers=min(16, len(items))) as pool:
        return list(pool.map(apply, items))


def parse_votes(data):
    if not isinstance(data, dict):
        return None
    return {
        'likes': data.get('likes') or 0,
        'dislikes': data.get('dislikes') or 0,
        'rating': data.get('rating') or 0,
    }


def fetch_votes(video_id, opener=None):
    url = RYD_API.format(video_id=urllib.parse.quote(video_id))
    return parse_votes(_get_json(url, opener))


_CATEGORY_GROUPS = {
    'sponsorblock_sponsor': ('sponsor', 'selfpromo'),
    'sponsorblock_intro_outro': ('intro', 'outro', 'preview', 'hook'),
    'sponsorblock_interaction': ('interaction',),
    'sponsorblock_filler': ('filler', 'music_offtopic', 'poi_highlight'),
}


def categories_for(settings):
    """Map add-on SponsorBlock toggle settings to API categories.

    settings is a plain dict so the service and tests share this logic;
    an empty list means SponsorBlock is effectively off.
    """
    if not settings.get('sponsorblock', True):
        return []
    categories = []
    for setting_id, group in _CATEGORY_GROUPS.items():
        if settings.get(setting_id, True):
            categories.extend(group)
    return categories
