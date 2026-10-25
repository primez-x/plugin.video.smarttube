# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - plugin entry point.

    Browsing, search and playback with no API key and no sign-in.
    See innertube.py for the network layer and routes.py for the
    plugin.video.youtube-compatible URL shapes.

    SPDX-License-Identifier: GPL-2.0-only
"""

import sys
from urllib.parse import parse_qs, urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

sys.path.insert(0, ADDON.getAddonInfo('path') + 'resources/lib')

import extras  # noqa: E402
import innertube  # noqa: E402
import routes  # noqa: E402

CHANNEL_VIDEOS_PARAMS = 'EgZ2aWRlb3M%3D'


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


def _add_item(handle, base, item):
    if item['type'] == 'video':
        if item.get('is_live') and item.get('channel_id'):
            url = routes.build_url(base, 'play', channel_id=item['channel_id'], live=1)
        else:
            url = routes.build_url(base, 'play', video_id=item['id'])
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
    list_item.setProperty('Starlight.Source', 'YouTube')
    list_item.setProperty('IsLive', 'true' if item.get('is_live') else 'false')
    list_item.setProperty('Starlight.IsLive', 'true' if item.get('is_live') else 'false')
    list_item.setProperty('IsPlayable', 'false' if is_folder else 'true')
    channel_id = item['id'] if item['type'] == 'channel' else item.get('channel_id')
    if channel_id:
        list_item.setProperty('SmartTube.ChannelId', channel_id)
        followed = (ADDON.getSetting('followed_channels') or '').replace(',', ' ').split()
        label = ADDON.getLocalizedString(32018 if channel_id in followed else 32017)
        list_item.addContextMenuItems([(label, 'RunPlugin(%s)' % routes.build_url(
            base, 'follow', channel_id=channel_id))])
    xbmcplugin.addDirectoryItem(handle, url, list_item, is_folder)


def _finish_listing(handle, succeeded=True):
    xbmcplugin.setContent(handle, 'videos')
    if succeeded:
        xbmcplugin.endOfDirectory(handle)
    else:
        xbmcplugin.endOfDirectory(handle, succeeded=False)


def _show_items(handle, base, items, continuation, route):
    if _setting_bool('dearrow', True):
        items = extras.apply_dearrow(items)
    for item in items:
        _add_item(handle, base, item)
    if continuation:
        if route.action == 'search':
            url = routes.build_url(base, 'search', q=route.query,
                                   continuation=continuation)
        elif route.action == 'channel':
            url = routes.build_url(base, 'channel/' + route.channel_id,
                                   continuation=continuation)
        elif route.action == 'playlist':
            url = routes.build_url(base, 'playlist/' + route.playlist_id,
                                   continuation=continuation)
        else:
            url = routes.build_url(base, 'browse/' + route.browse_id,
                                   continuation=continuation)
        next_item = xbmcgui.ListItem(
            label=ADDON.getLocalizedString(32012))
        xbmcplugin.addDirectoryItem(handle, url, next_item, True)
    _finish_listing(handle)


def _home(handle, base):
    entries = (
        (32010, routes.build_url(base, 'search')),
        (32011, routes.build_url(base, 'browse/FEwhat_to_watch')),
        (32016, routes.build_url(base, 'live_now')),
    )
    for string_id, url in entries:
        xbmcplugin.addDirectoryItem(
            handle, url,
            xbmcgui.ListItem(label=ADDON.getLocalizedString(string_id)),
            True)
    _finish_listing(handle)


def _resolve_play(handle, video_id):
    language, region = _locale()
    try:
        info, client_name = innertube.get_playback(
            video_id, hl=language, gl=region)
    except innertube.InnertubeError as exc:
        _log('Playback failed for %s: %s' % (video_id, exc),
             xbmc.LOGWARNING)
        info, client_name = None, ''
    url, kind = innertube.choose_stream(info) if info else ('', '')
    if not url:
        reason = (info or {}).get('reason') or 'No playable streams'
        _notify(reason)
        xbmcplugin.setResolvedUrl(
            handle, False, xbmcgui.ListItem(path=''))
        return
    _log('Playing %s via %s (%s)' % (video_id, client_name, kind))
    # The SponsorBlock service skips only while Kodi plays this stream.
    home = xbmcgui.Window(10000)
    home.setProperty('SmartTube.VideoId', video_id)
    home.setProperty('SmartTube.StreamUrl', url)
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
        for item in items:
            _add_item(handle, base, item)
        _finish_listing(handle)
    elif items:
        _resolve_play(handle, items[0]['id'])
    else:
        _notify(ADDON.getLocalizedString(32019))
        xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem(path=''))


def _live_now(handle, base, route):
    channels = innertube.channel_ids(ADDON.getSetting('followed_channels') or '')
    channels = innertube.channel_ids(channels + innertube.channel_ids(route.channel_ids))
    language, region = _locale()
    items, failures = innertube.live_now(channels, hl=language, gl=region)
    for item in items:
        _add_item(handle, base, item)
    if failures:
        _notify(ADDON.getLocalizedString(32023))
    xbmcplugin.setContent(handle, 'videos')
    if failures and len(failures) == len(channels):
        xbmcplugin.endOfDirectory(handle, succeeded=False)
    else:
        xbmcplugin.endOfDirectory(handle)


def _follow(channel_id):
    requested = innertube.channel_ids([channel_id])
    if not requested:
        raise ValueError('A channel ID is required')
    channels = innertube.channel_ids(ADDON.getSetting('followed_channels') or '')
    if channel_id in channels:
        channels.remove(channel_id)
    else:
        channels = innertube.channel_ids(channels + requested)
    ADDON.setSetting('followed_channels', ','.join(channels))
    xbmc.executebuiltin('Container.Refresh')


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    base = argv[0]
    handle = int(argv[1]) if len(argv) > 1 else -1
    query_string = argv[2][1:] if len(argv) > 2 else ''
    path = urlparse(base).path
    route = None
    try:
        route = routes.parse_route(path, query_string)
        language, region = _locale()
        if route.action == 'home':
            _home(handle, base)
        elif route.action == 'trailer':
            _trailer(handle, base, route)
        elif route.action == 'live_now':
            _live_now(handle, base, route)
        elif route.action == 'follow':
            _follow(route.channel_id)
        elif route.action == 'search':
            if not route.query and not route.continuation:
                query = xbmcgui.Dialog().input(
                    ADDON.getLocalizedString(32010))
                if not query:
                    _finish_listing(handle)
                    return
                xbmc.executebuiltin(
                    'Container.Update(%s)' % routes.build_url(
                        base, 'search', q=query))
                return
            items, continuation = innertube.search(
                route.query, continuation=route.continuation,
                hl=language, gl=region)
            _show_items(handle, base, items, continuation, route)
        elif route.action == 'browse':
            items, continuation = innertube.browse(
                route.browse_id, continuation=route.continuation,
                hl=language, gl=region)
            _show_items(handle, base, items, continuation, route)
        elif route.action == 'channel':
            items, continuation = innertube.browse(
                route.channel_id, params=CHANNEL_VIDEOS_PARAMS,
                continuation=route.continuation,
                hl=language, gl=region)
            _show_items(handle, base, items, continuation, route)
        elif route.action == 'playlist':
            browse_id = route.playlist_id
            if not browse_id.startswith('VL'):
                browse_id = 'VL' + browse_id
            items, continuation = innertube.browse(
                browse_id, continuation=route.continuation,
                hl=language, gl=region)
            _show_items(handle, base, items, continuation, route)
        elif route.action == 'play_channel':
            _play_channel_live(handle, route.channel_id)
        elif route.action == 'play':
            if route.video_id:
                _resolve_play(handle, route.video_id)
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
        elif not route or route.action != 'follow':
            _finish_listing(handle, succeeded=False)


if __name__ == '__main__':
    main()
