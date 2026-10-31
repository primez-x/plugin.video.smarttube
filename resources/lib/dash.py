# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - DASH manifests from YouTube adaptive formats.

    YouTube gives the player clients separate audio and video files with
    byte ranges for the index of each file. One static MPD lists them so
    inputstream.adaptive can play up to 4K and HDR.

    inputstream.adaptive seeks a WebM stream only to the start of a chunk
    but an MP4 stream to the exact sample, and the first video stream sets
    the time that later streams seek to. So video comes first and audio is
    MP4 only; otherwise audio starts seconds before video after a seek.

    inputstream.adaptive reads a manifest only over HTTP, so the service
    serves the written manifests on the loopback address.

    SPDX-License-Identifier: GPL-2.0-only
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import re
import threading
from xml.sax.saxutils import escape, quoteattr

HDR_TRANSFERS = ('COLOR_TRANSFER_CHARACTERISTICS_SMPTEST2084',
                 'COLOR_TRANSFER_CHARACTERISTICS_ARIB_STD_B67')


# 18 digits fit a 64 bit byte offset or duration
def _int(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10 ** 18


def _digits(value):
    return _int(value) or (isinstance(value, str) and value.isascii() and value.isdigit()
                           and len(value) <= 18)


def _byte_range(value):
    return (isinstance(value, dict) and _digits(value.get('start')) and _digits(value.get('end'))
            and int(value['start']) <= int(value['end']))


# The characters that XML 1.0 allows
_XML_TEXT = re.compile('[\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]*\\Z')


def _text(value):
    return isinstance(value, str) and _XML_TEXT.match(value) is not None


def _usable(fmt):
    """Check every field the manifest reads: YouTube data is untrusted."""
    if not isinstance(fmt, dict) or fmt.get('isDrc'):
        return False
    if not (_int(fmt.get('itag')) and _text(fmt.get('url')) and fmt['url']
            and _text(fmt.get('mimeType')) and fmt['mimeType']):
        return False
    if not all(_byte_range(fmt.get(key)) for key in ('initRange', 'indexRange')):
        return False
    if not all(fmt.get(key) is None or _int(fmt[key])
               for key in ('height', 'width', 'fps', 'bitrate', 'audioChannels')):
        return False
    if not all(fmt.get(key) in (None, '') or _digits(fmt[key])
               for key in ('approxDurationMs', 'audioSampleRate')):
        return False
    track = fmt.get('audioTrack')
    if track is not None and not (isinstance(track, dict) and all(
            track.get(key) is None or _text(track[key]) for key in ('id', 'displayName'))):
        return False
    return fmt.get('colorInfo') is None or isinstance(fmt['colorInfo'], dict)


def _mime(fmt):
    mime, _, rest = fmt['mimeType'].partition(';')
    return mime.strip(), rest.partition('codecs=')[2].strip().strip('"')


def _range(value):
    return '%s-%s' % (value['start'], value['end'])


def _hdr(fmt):
    return (fmt.get('colorInfo') or {}).get('transferCharacteristics') in HDR_TRANSFERS


def _video_set(formats, hdr):
    """VP9 when present (HDR only with an HDR display), else H.264; one frame rate."""
    videos = [fmt for fmt in formats if _mime(fmt)[0].startswith('video/') and fmt.get('height')]
    vp9 = [fmt for fmt in videos if _mime(fmt)[1].startswith(('vp9', 'vp09'))]
    hdr_vp9 = [fmt for fmt in vp9 if _hdr(fmt)]
    if hdr and hdr_vp9:
        chosen = hdr_vp9
    else:
        chosen = [fmt for fmt in vp9 if not _hdr(fmt)] or [
            fmt for fmt in videos if _mime(fmt)[1].startswith('avc1')]
    if not chosen:
        return []
    fps = max(fmt.get('fps') or 0 for fmt in chosen)
    chosen = [fmt for fmt in chosen if (fmt.get('fps') or 0) == fps]
    return sorted(chosen, key=lambda fmt: (fmt['height'], fmt.get('bitrate') or 0), reverse=True)


def _audio_sets(formats):
    """The best MP4 audio per track; the default track first."""
    best = {}
    for fmt in formats:
        if _mime(fmt)[0] != 'audio/mp4':
            continue
        track = fmt.get('audioTrack') or {}
        key = track.get('id') or ''
        if key not in best or (fmt.get('bitrate') or 0) > (best[key].get('bitrate') or 0):
            best[key] = fmt
    return sorted(best.values(), key=lambda fmt: (
        not (fmt.get('audioTrack') or {}).get('audioIsDefault', True),
        (fmt.get('audioTrack') or {}).get('id') or ''))


def _representation(fmt):
    mime, codecs = _mime(fmt)
    attributes = {'id': fmt['itag'], 'codecs': codecs, 'bandwidth': fmt.get('bitrate') or 0}
    if mime.startswith('video/'):
        attributes.update(width=fmt.get('width') or 0, height=fmt['height'], frameRate=fmt.get('fps') or 0)
    else:
        attributes['audioSamplingRate'] = fmt.get('audioSampleRate') or 44100
    lines = ['   <Representation %s>' % ' '.join(
        '%s=%s' % (name, quoteattr(str(value))) for name, value in attributes.items())]
    if mime.startswith('audio/'):
        lines.append('    <AudioChannelConfiguration schemeIdUri='
                     '"urn:mpeg:dash:23003:3:audio_channel_configuration:2011" value="%d"/>'
                     % (fmt.get('audioChannels') or 2))
    lines += ['    <BaseURL>%s</BaseURL>' % escape(fmt['url']),
              '    <SegmentBase indexRange="%s">' % _range(fmt['indexRange']),
              '     <Initialization range="%s"/>' % _range(fmt['initRange']),
              '    </SegmentBase>',
              '   </Representation>']
    return lines


def manifest(formats, hdr=False):
    """Return a static MPD for the adaptive formats, or None without video and MP4 audio."""
    formats = sorted((fmt for fmt in formats or [] if _usable(fmt)),
                     key=lambda fmt: (fmt['itag'], fmt['url']))
    videos, audios = _video_set(formats, hdr), _audio_sets(formats)
    if not videos or not audios:
        return None
    duration = divmod(max(int(fmt.get('approxDurationMs') or 0) for fmt in videos + audios), 1000)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" minBufferTime="PT1.5S"'
             ' mediaPresentationDuration="PT%d.%03dS" profiles="urn:mpeg:dash:profile:isoff-on-demand:2011">'
             % duration,
             ' <Period>',
             '  <AdaptationSet contentType="video" mimeType=%s subsegmentAlignment="true">'
             % quoteattr(_mime(videos[0])[0])]
    for fmt in videos:
        lines += _representation(fmt)
    lines.append('  </AdaptationSet>')
    for index, fmt in enumerate(audios):
        track = fmt.get('audioTrack') or {}
        attributes = ' contentType="audio" mimeType="audio/mp4"'
        if track.get('id'):
            # name and original are inputstream.adaptive attributes.
            attributes += ' lang=%s name=%s' % (
                quoteattr(track['id'].partition('.')[0]), quoteattr(track.get('displayName') or ''))
            if track.get('audioIsDefault'):
                attributes += ' original="true"'
        lines.append('  <AdaptationSet%s>' % attributes)
        if index == 0 and len(audios) > 1:
            lines.append('   <Role schemeIdUri="urn:mpeg:dash:role:2011" value="main"/>')
        lines += _representation(fmt)
        lines.append('  </AdaptationSet>')
    lines += [' </Period>', '</MPD>', '']
    return '\n'.join(lines)


MANIFEST_NAME = re.compile(r'dash-[A-Za-z0-9_-]+\.mpd')


def manifest_name(video_id):
    """The file name of the manifest, or None for a video ID that is not a plain name."""
    name = 'dash-%s.mpd' % video_id
    return name if MANIFEST_NAME.fullmatch(name) else None


class ManifestServer(object):
    """Serve the dash-<video id>.mpd files of one directory on 127.0.0.1."""

    address = '127.0.0.1'

    def __init__(self, directory, port=0):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                name = self.path.lstrip('/')
                try:
                    if not MANIFEST_NAME.fullmatch(name):
                        raise OSError('not a manifest')
                    with open(os.path.join(directory, name), 'rb') as handle:
                        body = handle.read()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/dash+xml')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer((self.address, port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, name):
        return 'http://%s:%d/%s' % (self.address, self.port, name)

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
