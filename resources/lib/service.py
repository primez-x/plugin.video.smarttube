# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - SponsorBlock skip service.

    The plugin resolver stores the video id and the stream URL it resolved
    in the Home window properties SmartTube.VideoId and SmartTube.StreamUrl.
    This service skips only while Kodi plays that exact stream: it fetches
    the SponsorBlock segments once per file and seeks past them.

    SPDX-License-Identifier: GPL-2.0-only
"""

import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')

sys.path.insert(0, ADDON.getAddonInfo('path') + 'resources/lib')

import extras  # noqa: E402

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


def main():
    monitor = xbmc.Monitor()
    player = xbmc.Player()
    home = xbmcgui.Window(10000)
    loaded_for = ''
    skips = None
    xbmc.log('[%s] SponsorBlock service started' % ADDON_ID, xbmc.LOGINFO)
    while not monitor.abortRequested():
        playing_file = _playing_file(player)
        if playing_file != loaded_for:
            loaded_for = playing_file
            skips = None
            video_id = home.getProperty('SmartTube.VideoId')
            if (playing_file and video_id
                    and playing_file == home.getProperty('SmartTube.StreamUrl')):
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
        if skips is not None:
            try:
                segment = skips.check(player.getTime())
                total_time = player.getTotalTime()
            except RuntimeError:
                segment = None
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
    xbmc.log('[%s] SponsorBlock service stopped' % ADDON_ID, xbmc.LOGINFO)


if __name__ == '__main__':
    main()
