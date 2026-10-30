# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - SponsorBlock skip and watch history service.

    The plugin resolver stores the video id and the stream URL it resolved
    in the Home window properties SmartTube.VideoId and SmartTube.StreamUrl.
    This service acts only while Kodi plays that exact stream: it fetches
    the SponsorBlock segments once per file and seeks past them. When the
    resolver also stores SmartTube.Item, the service is the only writer of
    the watch history and saves the playback position.

    SPDX-License-Identifier: GPL-2.0-only
"""

import json
import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

sys.path.insert(0, ADDON.getAddonInfo('path') + 'resources/lib')

import extras  # noqa: E402
import library  # noqa: E402

STORE = library.Store(PROFILE)
SAVE_INTERVAL = 30
# Longer than the longest plugin cache lifetime (channel metadata, 7 days).
CACHE_MAX_AGE = 8 * 86400

_SETTING_IDS = (
    'sponsorblock', 'sponsorblock_sponsor', 'sponsorblock_intro_outro',
    'sponsorblock_interaction', 'sponsorblock_filler', 'sponsorblock_notify',
)


def _settings():
    values = {}
    for setting_id in _SETTING_IDS:
        try:
            values[setting_id] = ADDON.getSettingBool(setting_id)
        except Exception:
            values[setting_id] = True
    return values


def _playing_file(player):
    try:
        return player.getPlayingFile() if player.isPlayingVideo() else ''
    except RuntimeError:
        return ''


def _end_playback(player):
    """Leave the video as a natural end would: next queued video, else stop."""
    position = xbmc.getInfoLabel('VideoPlayer.PlaylistPosition')
    length = xbmc.getInfoLabel('VideoPlayer.PlaylistLength')
    if position.isdigit() and length.isdigit() and int(position) < int(length):
        player.playnext()
    else:
        player.stop()


def _history_item(home, video_id):
    try:
        item = json.loads(home.getProperty('SmartTube.Item') or 'null')
    except ValueError:
        return None
    return item if isinstance(item, dict) and item.get('id') == video_id else None


def _record(item, position=None, total=None, create=False):
    """Save progress; later saves never re-add a video the user removed."""
    try:
        STORE.record_progress(item, position, total, create=create)
    except (OSError, ValueError) as exc:
        xbmc.log('[%s] Watch history not saved: %s' % (ADDON_ID, exc),
                 xbmc.LOGWARNING)


def main():
    monitor = xbmc.Monitor()
    player = xbmc.Player()
    home = xbmcgui.Window(10000)
    try:
        STORE.migrate_follows(lambda: library.legacy_setting(PROFILE, 'followed_channels'))
    except OSError as exc:
        xbmc.log('[%s] Followed channels not migrated: %s' % (ADDON_ID, exc),
                 xbmc.LOGWARNING)
    library.Cache(os.path.join(PROFILE, 'cache')).prune(CACHE_MAX_AGE)
    loaded_for = ''
    skips = None
    watched = None
    position = total = None
    sample = None
    saved_at = 0
    xbmc.log('[%s] SponsorBlock service started' % ADDON_ID, xbmc.LOGINFO)
    while not monitor.abortRequested():
        playing_file = _playing_file(player)
        if playing_file != loaded_for:
            if watched is not None and position is not None:
                _record(watched, position, total)
            loaded_for = playing_file
            skips = None
            watched = None
            sample = None
            video_id = home.getProperty('SmartTube.VideoId')
            if (playing_file and video_id
                    and playing_file == home.getProperty('SmartTube.StreamUrl')):
                watched = _history_item(home, video_id)
                position = total = None
                if watched is not None:
                    # Keep a stored resume point until Kodi reports a position.
                    _record(watched, create=True)
                    saved_at = time.time()
                settings = _settings()
                categories = extras.categories_for(settings)
                if categories:
                    try:
                        segments = extras.fetch_segments(
                            video_id, categories)
                        xbmc.log(
                            '[%s] %d SponsorBlock segment(s) for %s'
                            % (ADDON_ID, len(segments), video_id),
                            xbmc.LOGINFO)
                        skips = extras.SegmentSkips(segments)
                    except Exception as exc:
                        xbmc.log(
                            '[%s] SponsorBlock lookup failed: %s'
                            % (ADDON_ID, exc), xbmc.LOGWARNING)
        previous, sample = sample, None
        if watched is not None or skips is not None:
            try:
                sample, total_time = player.getTime(), player.getTotalTime()
            except RuntimeError:
                pass
        # Act only on a position that continues the previous sample.
        if extras.steady(previous, sample):
            if watched is not None:
                position, total = sample, total_time or total
                if time.time() - saved_at >= SAVE_INTERVAL:
                    _record(watched, position, total)
                    saved_at = time.time()
            segment = skips.check(sample) if skips is not None else None
            if segment is not None:
                if extras.ends_video(segment, total_time):
                    _end_playback(player)
                else:
                    player.seekTime(segment['end'])
                if _settings().get('sponsorblock_notify', True):
                    xbmcgui.Dialog().notification(
                        ADDON.getAddonInfo('name'),
                        ADDON.getLocalizedString(32015),
                        ADDON.getAddonInfo('icon'), 2500)
        if monitor.waitForAbort(1):
            break
    if watched is not None and position is not None:
        _record(watched, position, total)
    xbmc.log('[%s] SponsorBlock service stopped' % ADDON_ID, xbmc.LOGINFO)


if __name__ == '__main__':
    main()
