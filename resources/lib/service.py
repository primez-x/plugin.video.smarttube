# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - SponsorBlock skip service.

    The plugin resolver stores the playing video id in the Home window
    property SmartTube.VideoId; this service fetches its SponsorBlock
    segments once per file and seeks past them during playback.

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


def main():
    monitor = xbmc.Monitor()
    player = xbmc.Player()
    home = xbmcgui.Window(10000)
    loaded_for = ''
    segments = []
    xbmc.log('[%s] SponsorBlock service started' % ADDON_ID, xbmc.LOGINFO)
    while not monitor.abortRequested():
        try:
            playing = player.isPlayingVideo()
        except RuntimeError:
            playing = False
        if playing:
            video_id = home.getProperty('SmartTube.VideoId')
            if video_id and video_id != loaded_for:
                loaded_for = video_id
                segments = []
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
                    except Exception as exc:
                        xbmc.log(
                            '[%s] SponsorBlock lookup failed: %s'
                            % (ADDON_ID, exc), xbmc.LOGWARNING)
            if segments:
                try:
                    segment = extras.segment_at(segments, player.getTime())
                except RuntimeError:
                    segment = None
                if segment is not None:
                    player.seekTime(segment['end'])
                    if _settings().get('sponsorblock_notify', True):
                        xbmcgui.Dialog().notification(
                            ADDON.getAddonInfo('name'),
                            ADDON.getLocalizedString(32015),
                            ADDON.getAddonInfo('icon'), 2500)
        else:
            loaded_for = ''
            segments = []
        if monitor.waitForAbort(1):
            break
    xbmc.log('[%s] SponsorBlock service stopped' % ADDON_ID, xbmc.LOGINFO)


if __name__ == '__main__':
    main()
