# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - plugin entry point.

    Browsing, search and playback with no API key and no sign-in.
    See innertube.py for the network layer, library.py for the local
    subscriptions, history and saved lists, and routes.py for the
    plugin.video.youtube-compatible URL shapes.

    SPDX-License-Identifier: GPL-2.0-only
"""

import json
import os
import sys
from urllib.parse import parse_qs, urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

sys.path.insert(0, ADDON.getAddonInfo('path') + 'resources/lib')

import dash  # noqa: E402
import extras  # noqa: E402
import innertube  # noqa: E402
import library  # noqa: E402
import routes  # noqa: E402

CHANNEL_VIDEOS_PARAMS = 'EgZ2aWRlb3M%3D'
STORE = library.Store(PROFILE)
CACHE = library.Cache(os.path.join(PROFILE, 'cache'))
PAGE_SIZE = 60
FEED_TTL = 15 * 60
LIVE_TTL = 5 * 60
RELATED_TTL = 6 * 3600
CHART_TTL = 6 * 3600
CHANNEL_TTL = 7 * 86400
DEARROW_TTL = 86400
# Fields kept for saved videos, channels and playlists.
_ITEM_FIELDS = ('type', 'id', 'title', 'author', 'thumbnail', 'duration',
                'channel_id', 'views', 'published', 'is_live')

# (string, path, icon) for the main menu; hubs and widgets use the same paths.
SECTIONS = (
    (32050, 'subscriptions', 'DefaultRecentlyAddedEpisodes.png'),
    (32051, 'continue', 'DefaultInProgressShows.png'),
    (32052, 'recommended', 'DefaultFavourites.png'),
    (32053, 'trending', 'DefaultMusicTop100.png'),
    (32016, 'live_now', 'DefaultAddonPVRClient.png'),
    (32054, 'history', 'DefaultMusicRecentlyPlayed.png'),
    (32055, 'watch_later', 'DefaultVideoPlaylists.png'),
    (32056, 'channels', 'DefaultUser.png'),
    (32057, 'playlists', 'DefaultPlaylist.png'),
    (32010, 'search', 'DefaultAddonsSearch.png'),
    (32059, 'explore/music', 'DefaultMusicVideos.png'),
    (32060, 'explore/gaming', 'DefaultGameAddons.png'),
    (32061, 'explore/news', 'DefaultGenre.png'),
    (32062, 'explore/sports', 'DefaultGenre.png'),
    (32063, 'explore/live', 'DefaultAddonPVRClient.png'),
    (32064, 'explore/learning', 'DefaultGenre.png'),
    (32065, 'explore/fashion', 'DefaultGenre.png'),
)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def _notify(message):
    xbmcgui.Dialog().notification(
        ADDON.getAddonInfo('name'), message,
        ADDON.getAddonInfo('icon'), 4000)


def _setting_bool(setting_id, default=False):
    try:
        return ADDON.getSettingBool(setting_id)
    except Exception:
        return default


def _locale():
    language = ADDON.getSetting('language') or 'en'
    region = ADDON.getSetting('region') or 'US'
    return language, region


class _Saved(object):
    """IDs in the local lists, loaded once per listing for context menus."""

    def __init__(self):
        self.follows = set(entry['id'] for entry in STORE.load('follows'))
        self.watch_later = set(entry['id'] for entry in STORE.load('watch_later'))
        self.playlists = set(entry['id'] for entry in STORE.load('playlists'))
        self.resume = library.resume_points(STORE.load('history'))


def _manage_url(base, op, list_name, item):
    if op == 'add':
        saved = dict((key, item[key]) for key in _ITEM_FIELDS if item.get(key))
        return routes.build_url(base, 'manage', op=op, list=list_name,
                                item=json.dumps(saved, ensure_ascii=False))
    return routes.build_url(base, 'manage', op=op, list=list_name, id=item['id'])


def _toggle(base, label_add, label_remove, list_name, item, saved):
    op = 'remove' if saved else 'add'
    return (ADDON.getLocalizedString(label_remove if saved else label_add),
            'RunPlugin(%s)' % _manage_url(base, op, list_name, item))


def _open(base, path, **params):
    return 'ActivateWindow(Videos,%s,return)' % routes.build_url(base, path, **params)


def _context_menu(base, item, saved, extra):
    menu = []
    channel_id = item['id'] if item['type'] == 'channel' else item.get('channel_id')
    if item['type'] == 'video':
        if channel_id:
            menu.append((ADDON.getLocalizedString(32070), _open(base, 'channel/' + channel_id)))
        menu.append((ADDON.getLocalizedString(32071), _open(base, 'related', video_id=item['id'])))
        menu.append(_toggle(base, 32072, 32073, 'watch_later', item,
                            item['id'] in saved.watch_later))
    elif item['type'] == 'playlist':
        menu.append(_toggle(base, 32076, 32077, 'playlists', item,
                            item['id'] in saved.playlists))
    if channel_id:
        channel = {'type': 'channel', 'id': channel_id,
                   'title': item['title'] if item['type'] == 'channel' else item.get('author'),
                   'thumbnail': item.get('thumbnail') if item['type'] == 'channel' else ''}
        menu.append(_toggle(base, 32017, 32018, 'follows', channel,
                            channel_id in saved.follows))
    return menu + list(extra)


def _add_item(handle, base, item, saved, extra=(), history=True):
    if item['type'] == 'video':
        if item.get('is_live') and item.get('channel_id'):
            url = routes.build_url(base, 'play', channel_id=item['channel_id'], live=1)
        else:
            url = routes.build_url(base, 'play', video_id=item['id'],
                                   history=1 if history else '')
        is_folder = False
    elif item['type'] == 'channel':
        url = routes.build_url(base, 'channel/' + item['id'])
        is_folder = True
    else:
        url = routes.build_url(base, 'playlist/' + item['id'])
        is_folder = True
    list_item = xbmcgui.ListItem(label=item.get('title') or item['id'])
    if item.get('thumbnail'):
        list_item.setArt({'thumb': item['thumbnail'],
                          'icon': item['thumbnail'],
                          'landscape': item['thumbnail'],
                          'fanart': item['thumbnail']})
    info = list_item.getVideoInfoTag()
    info.setTitle(item.get('title') or item['id'])
    if item.get('author'):
        info.setWriters([item['author']])
    plot_parts = [part for part in (item.get('author'), item.get('views'),
                                    item.get('published')) if part]
    if plot_parts:
        info.setPlot(' • '.join(plot_parts))
    if item.get('duration'):
        info.setDuration(item['duration'])
    if item['id'] in saved.resume:
        info.setResumePoint(*saved.resume[item['id']])
    list_item.setProperty('Starlight.Source', 'YouTube')
    list_item.setProperty('IsLive', 'true' if item.get('is_live') else 'false')
    list_item.setProperty('Starlight.IsLive', 'true' if item.get('is_live') else 'false')
    list_item.setProperty('IsPlayable', 'false' if is_folder else 'true')
    channel_id = item['id'] if item['type'] == 'channel' else item.get('channel_id')
    if channel_id:
        list_item.setProperty('SmartTube.ChannelId', channel_id)
    list_item.addContextMenuItems(_context_menu(base, item, saved, extra))
    xbmcplugin.addDirectoryItem(handle, url, list_item, is_folder)


def _add_folder(handle, url, label, icon='DefaultFolder.png', context=()):
    list_item = xbmcgui.ListItem(label=label)
    list_item.setArt({'icon': icon, 'thumb': icon})
    list_item.addContextMenuItems(list(context))
    xbmcplugin.addDirectoryItem(handle, url, list_item, True)


def _finish_listing(handle, succeeded=True):
    xbmcplugin.setContent(handle, 'videos')
    if succeeded:
        xbmcplugin.endOfDirectory(handle)
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def _next_url(base, route, continuation):
    if route.action == 'search':
        return routes.build_url(base, 'search', q=route.query, continuation=continuation)
    if route.action == 'channel':
        return routes.build_url(base, 'channel/' + route.channel_id, continuation=continuation)
    if route.action == 'playlist':
        return routes.build_url(base, 'playlist/' + route.playlist_id, continuation=continuation)
    return routes.build_url(base, 'browse/' + route.browse_id, continuation=continuation)


def _show_items(handle, base, items, next_url='', extra=None):
    """List items; extra(item) adds section-specific context menu entries."""
    if _setting_bool('dearrow', True):
        items = extras.apply_dearrow(items, fetch=lambda video_id: CACHE.get(
            'dearrow:' + video_id, DEARROW_TTL, lambda: extras.fetch_branding(video_id)))
    saved = _Saved()
    for item in items:
        _add_item(handle, base, item, saved, extra(item) if extra else ())
    if next_url:
        _add_folder(handle, next_url, ADDON.getLocalizedString(32012))
    _finish_listing(handle)


def _show_listing(handle, base, route, listing):
    """List one InnerTube page with a link to the next one."""
    items, continuation = listing
    _show_items(handle, base, items,
                _next_url(base, route, continuation) if continuation else '')


def _page_path(route):
    return 'explore/' + route.category if route.action == 'explore' else route.action


def _show_page(handle, base, items, route, extra=None):
    """List one page of a local list."""
    start = (route.page - 1) * PAGE_SIZE
    more = len(items) > start + PAGE_SIZE
    _show_items(handle, base, items[start:start + PAGE_SIZE],
                routes.build_url(base, _page_path(route), page=route.page + 1) if more else '',
                extra)


def _home(handle, base):
    for string_id, path, icon in SECTIONS:
        _add_folder(handle, routes.build_url(base, path),
                    ADDON.getLocalizedString(string_id), icon)
    _finish_listing(handle)


def _hdr_output():
    """True when Kodi can show HDR video from an inputstream add-on.

    Kodi 21 passes the colour data of add-on streams but never sets the HDR
    type, so the display shows HDR video as SDR with wrong colours. Kodi 22
    sets the type (xbmc commit 085c4d3, "[InputStreamAddon] Implemented HDR
    types").
    """
    major = xbmc.getInfoLabel('System.BuildVersion').partition('.')[0]
    return (major.isdigit() and int(major) >= 22
            and bool(xbmc.getInfoLabel('System.SupportedHDRTypes')))


def _dash_manifest(video_id, info):
    """Write the MPD of a video that is not live; return (url, 'dash') or ('', '').

    The service serves the cache directory on SmartTube.ManifestPort.
    """
    port = xbmcgui.Window(10000).getProperty('SmartTube.ManifestPort')
    if info.get('is_live') or not port.isdigit():
        return '', ''
    manifest = dash.manifest(info.get('adaptive'), hdr=_hdr_output())
    if not manifest:
        return '', ''
    # One file per video: the service treats a new URL as a new video.
    # The service prunes old files with the rest of the cache.
    name = dash.manifest_name(video_id)
    library.write_text(os.path.join(CACHE.directory, name), manifest)
    return 'http://127.0.0.1:%s/%s' % (port, name), 'dash'


def _resolve_play(handle, video_id, history=False):
    language, region = _locale()
    try:
        info, client_name = innertube.get_playback(
            video_id, hl=language, gl=region)
    except innertube.InnertubeError as exc:
        _log('Playback failed for %s: %s' % (video_id, exc),
             xbmc.LOGWARNING)
        info, client_name = None, ''
    url, kind = _dash_manifest(video_id, info) if info else ('', '')
    if not url:
        url, kind = innertube.choose_stream(info) if info else ('', '')
    if not url:
        reason = (info or {}).get('reason') or 'No playable streams'
        _notify(reason)
        xbmcplugin.setResolvedUrl(
            handle, False, xbmcgui.ListItem(path=''))
        return
    _log('Playing %s via %s (%s)' % (video_id, client_name, kind))
    # The service skips SponsorBlock segments and records the watch history
    # only while Kodi plays this stream.
    home = xbmcgui.Window(10000)
    home.setProperty('SmartTube.VideoId', video_id)
    home.setProperty('SmartTube.StreamUrl', url)
    home.setProperty('SmartTube.Item', json.dumps({
        'type': 'video', 'id': video_id, 'title': info.get('title') or video_id,
        'author': info.get('author') or '', 'channel_id': info.get('channel_id') or '',
        'thumbnail': 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % video_id,
        'duration': info.get('length_seconds') or 0, 'is_live': info.get('is_live'),
    }) if history else '')
    list_item = xbmcgui.ListItem(path=url)
    list_item.setProperty('Starlight.Source', 'YouTube')
    list_item.setProperty('IsLive', 'true' if info.get('is_live') else 'false')
    list_item.setProperty('Starlight.IsLive', 'true' if info.get('is_live') else 'false')
    video_info = list_item.getVideoInfoTag()
    video_info.setTitle(info.get('title') or video_id)
    if info.get('author'):
        video_info.setWriters([info['author']])
    if info.get('length_seconds'):
        video_info.setDuration(info['length_seconds'])
    if _setting_bool('dislikes', False):
        try:
            votes = extras.fetch_votes(video_id)
        except Exception:
            votes = None
        if votes:
            video_info.setPlot('Likes %s · Dislikes %s' % (
                votes['likes'], votes['dislikes']))
    if kind in ('dash', 'hls'):
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        list_item.setProperty(
            'inputstream.adaptive.manifest_type',
            'mpd' if kind == 'dash' else 'hls')
        list_item.setMimeType(
            'application/dash+xml' if kind == 'dash'
            else 'application/vnd.apple.mpegurl')
    subtitles = [track['url'] + '&fmt=vtt' if '?' in track['url']
                 else track['url'] + '?fmt=vtt'
                 for track in info.get('captions') or []]
    if subtitles:
        list_item.setSubtitles(subtitles)
    xbmcplugin.setResolvedUrl(handle, True, list_item)


def _live_lookup(channel_id):
    language, region = _locale()
    return CACHE.get('live:' + channel_id, LIVE_TTL, lambda: innertube.channel_live(
        channel_id, hl=language, gl=region))


def _play_channel_live(handle, channel_id):
    language, region = _locale()
    live, failures = innertube.live_now([channel_id], hl=language, gl=region)
    if failures:
        _log('Live channel lookup failed', xbmc.LOGWARNING)
    if not live:
        _notify(ADDON.getLocalizedString(32013))
        xbmcplugin.setResolvedUrl(
            handle, False, xbmcgui.ListItem(path=''))
        return
    _resolve_play(handle, live[0]['id'])


def _trailer(handle, base, route):
    language, region = _locale()
    items = innertube.find_trailers(
        route.title, route.year, route.media_type, hl=language, gl=region)
    if route.mode == 'lookup':
        # Preserve the original title and art used by the trailer rank.
        saved = _Saved()
        for item in items:
            _add_item(handle, base, item, saved, history=False)
        _finish_listing(handle)
    elif items:
        _resolve_play(handle, items[0]['id'])
    else:
        _notify(ADDON.getLocalizedString(32019))
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem(path=''))


def _followed_ids():
    return [entry['id'] for entry in STORE.load('follows')]


def _live_now(handle, base, route):
    channels = innertube.channel_ids(_followed_ids() + innertube.channel_ids(route.channel_ids))
    items, failures = innertube.live_now(channels, lookup=_live_lookup)
    saved = _Saved()
    for item in items:
        _add_item(handle, base, item, saved)
    if failures:
        _notify(ADDON.getLocalizedString(32023))
    _finish_listing(handle, not failures or len(failures) < len(channels))


def _subscriptions(handle, base, route):
    channels = _followed_ids()
    items, failures = innertube.subscriptions(channels, fetch=lambda channel_id: CACHE.get(
        'feed:' + channel_id, FEED_TTL, lambda: innertube.channel_feed(channel_id)))
    if failures:
        _log('Feeds failed for %s' % ', '.join(failures), xbmc.LOGWARNING)
    if failures and len(failures) == len(channels):
        _notify(ADDON.getLocalizedString(32084))
        _finish_listing(handle, False)
        return
    _show_page(handle, base, items, route)


def _history_context(base):
    clear = (ADDON.getLocalizedString(32075), 'RunPlugin(%s)' % routes.build_url(
        base, 'manage', op='clear', list='history'))
    return lambda item: [(ADDON.getLocalizedString(32074), 'RunPlugin(%s)' % _manage_url(
        base, 'remove', 'history', item)), clear]


def _channels(handle, base):
    follows = STORE.load('follows')
    missing = [entry['id'] for entry in follows
               if not entry.get('title') or not entry.get('thumbnail')]
    if missing:
        language, region = _locale()
        found, _ = innertube._parallel(lambda channel_id: CACHE.get(
            'channel:' + channel_id, CHANNEL_TTL, lambda: innertube.channel_metadata(
                channel_id, hl=language, gl=region)), missing)
        if found:
            STORE.update('follows', found)
            follows = STORE.load('follows')
    _add_folder(handle, routes.build_url(base, 'import_subscriptions'),
                ADDON.getLocalizedString(32081), 'DefaultAddSource.png')
    channels = sorted((dict(entry, type='channel') for entry in follows),
                      key=lambda entry: (entry.get('title') or entry['id']).casefold())
    saved = _Saved()
    for channel in channels:
        _add_item(handle, base, channel, saved)
    _finish_listing(handle)


def _search_menu(handle, base):
    _add_folder(handle, routes.build_url(base, 'search/new'),
                ADDON.getLocalizedString(32058), 'DefaultAddonsSearch.png')
    clear = (ADDON.getLocalizedString(32079), 'RunPlugin(%s)' % routes.build_url(
        base, 'manage', op='clear', list='searches'))
    for entry in STORE.load('searches'):
        _add_folder(handle, routes.build_url(base, 'search', q=entry['id']),
                    entry['id'], 'DefaultAddonsSearch.png', context=[
                        (ADDON.getLocalizedString(32078), 'RunPlugin(%s)' % routes.build_url(
                            base, 'manage', op='remove', list='searches', id=entry['id'])),
                        clear])
    _finish_listing(handle)


def _search_prompt(handle, base):
    query = xbmcgui.Dialog().input(ADDON.getLocalizedString(32010)).strip()
    _finish_listing(handle, False)
    if query:
        STORE.add('searches', {'id': query})
        xbmc.executebuiltin('Container.Update(%s)' % routes.build_url(
            base, 'search', q=query))


def _import_subscriptions(handle):
    path = xbmcgui.Dialog().browseSingle(1, ADDON.getLocalizedString(32082), 'files', '.csv')
    if handle >= 0:
        _finish_listing(handle, False)
    if not path:
        return
    handle_file = xbmcvfs.File(path)
    try:
        text = handle_file.read()
    finally:
        handle_file.close()
    added = STORE.import_follows(library.parse_takeout_csv(text))
    _notify(ADDON.getLocalizedString(32083) % added)
    xbmc.executebuiltin('Container.Refresh')


def _manage(route):
    if route.op == 'clear' and not xbmcgui.Dialog().yesno(
            ADDON.getAddonInfo('name'), ADDON.getLocalizedString(32086)):
        return
    if route.op == 'add':
        if route.list_name == 'follows':
            innertube.channel_ids([route.item['id']])
        STORE.add(route.list_name, route.item)
    elif route.op == 'remove':
        STORE.remove(route.list_name, route.item['id'])
    else:
        STORE.clear(route.list_name)
    xbmc.executebuiltin('Container.Refresh')


def _section(handle, base, route):
    """List one app section; return False when the route is not a section."""
    language, region = _locale()
    if route.action == 'subscriptions':
        _subscriptions(handle, base, route)
    elif route.action == 'continue':
        _show_items(handle, base, library.continue_items(STORE.load('history')),
                    extra=_history_context(base))
    elif route.action == 'history':
        _show_page(handle, base, STORE.load('history'), route, extra=_history_context(base))
    elif route.action == 'watch_later':
        _show_page(handle, base, STORE.load('watch_later'), route)
    elif route.action == 'playlists':
        _show_page(handle, base, [dict(entry, type='playlist')
                                  for entry in STORE.load('playlists')], route)
    elif route.action == 'channels':
        _channels(handle, base)
    elif route.action == 'trending':
        chart = CACHE.get('chart:' + region, CHART_TTL, lambda: innertube.trending_chart(
            hl=language, gl=region))
        items, _ = innertube.trending(hl=language, gl=region, chart=chart)
        _show_items(handle, base, items)
    elif route.action == 'recommended':
        items = library.recommended(STORE.load('history'), lambda video_id: CACHE.get(
            'related:' + video_id, RELATED_TTL, lambda: innertube.related(
                video_id, hl=language, gl=region)))
        if not items:
            # New installs have no history yet; show what is popular instead.
            return _section(handle, base, routes.Route('trending'))
        _show_items(handle, base, items)
    elif route.action == 'related':
        _show_items(handle, base, innertube.related(
            route.video_id, hl=language, gl=region))
    elif route.action == 'explore':
        # Category pages return up to a few hundred videos in one response.
        items, _ = innertube.explore(route.category, hl=language, gl=region)
        _show_page(handle, base, items, route)
    elif route.action == 'live_now':
        _live_now(handle, base, route)
    elif route.action == 'search_menu':
        _search_menu(handle, base)
    else:
        return False
    return True


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    base = argv[0]
    handle = int(argv[1]) if len(argv) > 1 else -1
    query_string = argv[2][1:] if len(argv) > 2 else ''
    path = urlparse(base).path
    route = None
    try:
        route = routes.parse_route(path, query_string)
        STORE.migrate_follows(lambda: library.legacy_setting(PROFILE, 'followed_channels'))
        language, region = _locale()
        if route.action == 'home':
            _home(handle, base)
        elif _section(handle, base, route):
            pass
        elif route.action == 'trailer':
            _trailer(handle, base, route)
        elif route.action == 'manage':
            _manage(route)
        elif route.action == 'import_subscriptions':
            _import_subscriptions(handle)
        elif route.action == 'search_prompt':
            _search_prompt(handle, base)
        elif route.action == 'search':
            _show_listing(handle, base, route, innertube.search(
                route.query, continuation=route.continuation,
                hl=language, gl=region))
        elif route.action == 'browse':
            _show_listing(handle, base, route, innertube.browse(
                route.browse_id, continuation=route.continuation,
                hl=language, gl=region))
        elif route.action == 'channel':
            _show_listing(handle, base, route, innertube.browse(
                route.channel_id, params=CHANNEL_VIDEOS_PARAMS,
                continuation=route.continuation,
                hl=language, gl=region))
        elif route.action == 'playlist':
            browse_id = route.playlist_id
            if not browse_id.startswith('VL'):
                browse_id = 'VL' + browse_id
            _show_listing(handle, base, route, innertube.browse(
                browse_id, continuation=route.continuation,
                hl=language, gl=region))
        elif route.action == 'play_channel':
            _play_channel_live(handle, route.channel_id)
        elif route.action == 'play':
            if route.video_id:
                _resolve_play(handle, route.video_id, route.history)
            else:
                _notify(ADDON.getLocalizedString(32014))
                xbmcplugin.setResolvedUrl(
                    handle, False, xbmcgui.ListItem(path=''))
        else:
            _home(handle, base)
    except Exception as exc:  # Never leave Kodi spinning on an error.
        _log('Failed %s: %s' % (route, exc), xbmc.LOGERROR)
        _notify(str(exc))
        if (route and (route.action in ('play', 'play_channel')
                       or (route.action == 'trailer' and route.mode == 'play'))) or (
                route is None and path.strip('/') == 'trailer'
                and parse_qs(query_string).get('mode') != ['lookup']):
            xbmcplugin.setResolvedUrl(
                handle, False, xbmcgui.ListItem(path=''))
        elif handle >= 0 and not (route and route.action in (
                'manage', 'import_subscriptions', 'search_prompt')):
            _finish_listing(handle, succeeded=False)


if __name__ == '__main__':
    main()
