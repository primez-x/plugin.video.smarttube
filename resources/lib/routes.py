# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - plugin URL routing.

    Accepts SmartTube URLs for Starlight and the standard YouTube URL shapes:
      plugin://plugin.video.smarttube/search/?q=<QUERY>
      plugin://plugin.video.smarttube/kodion/search/query/?q=<QUERY>
      plugin://plugin.video.smarttube/play/?video_id=<VIDEO_ID>
      plugin://plugin.video.smarttube/channel/<CHANNEL_ID>
      plugin://plugin.video.smarttube/playlist/<PLAYLIST_ID>

    SPDX-License-Identifier: GPL-2.0-only
"""

import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit


class Route(object):
    def __init__(self, action='home', query='', video_id='', playlist_id='',
                 channel_id='', browse_id='', continuation='', live=False,
                 title='', year='', imdb='', tmdb='', media_type='',
                 mode='play', channel_ids=''):
        self.action = action
        self.query = query
        self.video_id = video_id
        self.playlist_id = playlist_id
        self.channel_id = channel_id
        self.browse_id = browse_id
        self.continuation = continuation
        self.live = live
        self.title = title
        self.year = year
        self.imdb = imdb
        self.tmdb = tmdb
        self.media_type = media_type
        self.mode = mode
        self.channel_ids = channel_ids

    def __repr__(self):
        return ('Route(action=%r, query=%r, video_id=%r, playlist_id=%r, '
                'channel_id=%r, browse_id=%r, live=%r)' % (
                    self.action, self.query, self.video_id,
                    self.playlist_id, self.channel_id, self.browse_id,
                    self.live))

    def __eq__(self, other):
        return isinstance(other, Route) and self.__dict__ == other.__dict__


def _first(params, *names):
    for name in names:
        values = params.get(name)
        if values and values[0]:
            return values[0]
    return ''


def parse_route(path, query_string=''):
    """Parse a Kodi plugin path + query string into a Route."""
    params = parse_qs(query_string or '')
    parts = [part for part in (path or '').split('/') if part]
    query = _first(params, 'q', 'query', 'search_query', 'search')
    video_id = _first(params, 'video_id', 'videoid', 'videoId', 'id')
    playlist_id = _first(params, 'playlist_id', 'playlistId')
    channel_id = _first(params, 'channel_id', 'channelId')
    continuation = _first(params, 'continuation', 'ctoken')
    browse_id = _first(params, 'browse_id', 'browseId')
    live = _first(params, 'live') not in ('', '0', 'false', 'False')
    if parts[:1] == ['trailer']:
        title = _first(params, 'title').strip()
        year = _first(params, 'year')
        media_type = _first(params, 'media_type')
        mode = _first(params, 'mode') or 'play'
        if not title or len(title) > 200 or not re.fullmatch(r'[12][0-9]{3}', year):
            raise ValueError('Trailer requires a title and a four-digit year')
        if media_type not in ('', 'movie', 'tv') or mode not in ('play', 'lookup'):
            raise ValueError('Invalid trailer media type or mode')
        return Route('trailer', title=title, year=year,
                     imdb=_first(params, 'imdb', 'imdb_id'),
                     tmdb=_first(params, 'tmdb', 'tmdb_id'),
                     media_type=media_type, mode=mode)
    if parts[:1] == ['live_now']:
        return Route('live_now', channel_ids=_first(params, 'channel_ids'))
    if parts[:1] == ['follow']:
        return Route('follow', channel_id=channel_id)
    # Standard YouTube play URLs for a channel's live stream.
    if parts[:1] == ['play'] and channel_id and not video_id:
        return Route('play_channel', channel_id=channel_id, live=True)
    if parts[:1] == ['play']:
        if playlist_id and not video_id:
            return Route('playlist', playlist_id=playlist_id,
                           continuation=continuation)
        return Route('play', video_id=video_id, playlist_id=playlist_id)
    if parts[:1] in (['search'], ['kodion']):
        return Route('search', query=query, continuation=continuation)
    if parts[:1] == ['channel'] and len(parts) >= 2:
        channel_id = channel_id or parts[1]
        if len(parts) >= 4 and parts[2] == 'playlist':
            return Route('playlist', playlist_id=parts[3],
                         continuation=continuation)
        if len(parts) >= 3 and parts[2] == 'live':
            return Route('play_channel', channel_id=channel_id, live=True)
        return Route('channel', channel_id=channel_id,
                     continuation=continuation)
    if parts[:1] == ['playlist'] and len(parts) >= 2:
        return Route('playlist', playlist_id=parts[1],
                     continuation=continuation)
    if parts[:1] == ['browse'] and len(parts) >= 2:
        return Route('browse', browse_id=parts[1],
                     continuation=continuation)
    if browse_id:
        return Route('browse', browse_id=browse_id,
                     continuation=continuation)
    if video_id:
        return Route('play', video_id=video_id)
    if query:
        return Route('search', query=query, continuation=continuation)
    return Route('home')


def build_url(base, path='', **params):
    """Build a plugin:// URL from the Kodi-provided base handle URL."""
    parsed = urlsplit(base)
    url = '%s://%s' % (parsed.scheme, parsed.netloc)
    if path:
        url += '/' + '/'.join(quote(part, safe='')
                              for part in path.strip('/').split('/')
                              if part) + '/'
    clean = dict((key, value) for key, value in params.items()
                 if value not in ('', None))
    if clean:
        url += '?' + urlencode(clean)
    return url
