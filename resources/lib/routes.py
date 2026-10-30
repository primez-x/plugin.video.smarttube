# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - plugin URL routing.

    Accepts SmartTube URLs for Starlight and the standard YouTube URL shapes:
      plugin://plugin.video.smarttube/search/?q=<QUERY>
      plugin://plugin.video.smarttube/kodion/search/query/?q=<QUERY>
      plugin://plugin.video.smarttube/play/?video_id=<VIDEO_ID>
      plugin://plugin.video.smarttube/channel/<CHANNEL_ID>
      plugin://plugin.video.smarttube/playlist/<PLAYLIST_ID>

    App sections for hubs and widgets: subscriptions, continue, history,
    watch_later, channels, playlists, trending, recommended, live_now and
    explore/<category>. manage/ changes the local lists.

    SPDX-License-Identifier: GPL-2.0-only
"""

import json
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit

SECTIONS = ('subscriptions', 'continue', 'history', 'watch_later', 'channels',
            'playlists', 'trending', 'recommended', 'import_subscriptions')
LISTS = ('follows', 'history', 'watch_later', 'playlists', 'searches')


class Route(object):
    def __init__(self, action='home', query='', video_id='', playlist_id='',
                 channel_id='', browse_id='', continuation='', live=False,
                 title='', year='', imdb='', tmdb='', media_type='',
                 mode='play', channel_ids='', category='', page=1,
                 history=False, op='', list_name='', item=None):
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
        self.category = category
        self.page = page
        self.history = history
        self.op = op
        self.list_name = list_name
        self.item = item

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


def _manage(params):
    op = _first(params, 'op')
    list_name = _first(params, 'list')
    if op not in ('add', 'remove', 'clear') or list_name not in LISTS:
        raise ValueError('Invalid list operation')
    item = None
    if op == 'add':
        try:
            item = json.loads(_first(params, 'item'))
        except ValueError:
            raise ValueError('Invalid list item')
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
            raise ValueError('Invalid list item')
    elif op == 'remove':
        item = {'id': _first(params, 'id')}
        if not item['id']:
            raise ValueError('A list item ID is required')
    return Route('manage', op=op, list_name=list_name, item=item)


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
    page = _first(params, 'page')
    page = int(page) if page.isdecimal() and int(page) > 0 else 1
    if parts[:1] and parts[0] in SECTIONS:
        return Route(parts[0], page=page)
    if parts[:1] == ['explore']:
        if len(parts) < 2:
            raise ValueError('A category is required')
        return Route('explore', category=parts[1], page=page)
    if parts[:1] == ['related']:
        if not video_id:
            raise ValueError('A video ID is required')
        return Route('related', video_id=video_id)
    if parts[:1] == ['manage']:
        return _manage(params)
    if parts[:2] == ['search', 'new']:
        return Route('search_prompt')
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
    # Standard YouTube play URLs for a channel's live stream.
    if parts[:1] == ['play'] and channel_id and not video_id:
        return Route('play_channel', channel_id=channel_id, live=True)
    if parts[:1] == ['play']:
        if playlist_id and not video_id:
            return Route('playlist', playlist_id=playlist_id,
                           continuation=continuation)
        return Route('play', video_id=video_id, playlist_id=playlist_id,
                     history=_first(params, 'history') == '1')
    if parts[:1] in (['search'], ['kodion']):
        if not query and not continuation:
            return Route('search_menu')
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
