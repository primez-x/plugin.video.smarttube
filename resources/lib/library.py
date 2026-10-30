# -*- coding: utf-8 -*-
"""
    SmartTube for Kodi - local library.

    Subscriptions, watch history, Watch later, saved playlists and search
    history live in JSON files in the add-on profile, so the app sections
    work signed out. Network responses are cached in the same profile
    because every plugin call runs in a new process.

    SPDX-License-Identifier: GPL-2.0-only
"""

import contextlib
import csv
import hashlib
import io
import json
import os
import tempfile
import time
from xml.etree import ElementTree

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

import innertube

LIMITS = {
    'follows': innertube.MAX_CHANNELS,
    'history': 500,
    'watch_later': 500,
    'playlists': 200,
    'searches': 50,
}
# Search terms match without case; YouTube IDs are case-sensitive.
_MATCH = {'searches': lambda key: key.casefold()}

CONTINUE_MIN_SECONDS = 30
WATCHED_FRACTION = 0.9


def _write_json(path, data):
    """Replace path atomically; each writer uses its own temporary file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=os.path.basename(path), suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise


@contextlib.contextmanager
def _locked(directory):
    """Serialize changes between the plugin processes and the service."""
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, 'store.lock'), 'a+') as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class Store(object):
    """Local lists; every change reads and writes the list under one lock."""

    def __init__(self, directory):
        self.directory = directory

    def _path(self, name):
        if name not in LIMITS:
            raise ValueError('Unknown list: %s' % name)
        return os.path.join(self.directory, name + '.json')

    def load(self, name):
        path = self._path(name)
        try:
            with open(path, encoding='utf-8') as handle:
                entries = json.load(handle)
            if not isinstance(entries, list):
                raise ValueError('not a list')
        except FileNotFoundError:
            return []
        except ValueError:
            # Keep an unreadable file for inspection instead of overwriting it.
            os.replace(path, path + '.bad')
            return []
        return [entry for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get('id'), str)]

    def _save(self, name, entries):
        _write_json(self._path(name), entries[:LIMITS[name]])

    def add(self, name, entry):
        match = _MATCH.get(name, lambda key: key)
        key = match(entry['id'])
        with _locked(self.directory):
            entries = [old for old in self.load(name) if match(old['id']) != key]
            self._save(name, [entry] + entries)

    def update(self, name, changes):
        """Merge changes[id] into the entries with that id; keep the order."""
        with _locked(self.directory):
            self._save(name, [dict(entry, **changes.get(entry['id'], {}))
                              for entry in self.load(name)])

    def remove(self, name, entry_id):
        with _locked(self.directory):
            entries = self.load(name)
            kept = [entry for entry in entries if entry['id'] != entry_id]
            if len(kept) != len(entries):
                self._save(name, kept)

    def clear(self, name):
        with _locked(self.directory):
            self._save(name, [])

    def record_progress(self, item, position=None, total=None, now=None, create=True):
        """Move the video to the top of the history with its playback position.

        Without a position the stored resume point stays. With create=False a
        video that the user removed from the history stays removed.
        """
        with _locked(self.directory):
            entries = self.load('history')
            previous = next((entry for entry in entries if entry['id'] == item['id']), None)
            if previous is None and not create:
                return
            entry = dict(previous or {}, **item)
            if position is None:
                position = entry.get('position', 0)
            if total is None:
                total = entry.get('total') or entry.get('duration') or 0
            entry.update(position=max(0, int(position)), total=max(0, int(total)),
                         watched_at=int(time.time() if now is None else now))
            self._save('history', [entry] + [old for old in entries if old['id'] != item['id']])

    def migrate_follows(self, read_legacy):
        """Import the channel IDs of the former settings field once."""
        if os.path.exists(self._path('follows')):
            return
        ids = []
        for channel_id in read_legacy().replace(',', ' ').split():
            try:
                ids += innertube.channel_ids([channel_id])
            except ValueError:
                continue
        with _locked(self.directory):
            if not os.path.exists(self._path('follows')):
                self._save('follows', [{'id': channel_id, 'title': '', 'thumbnail': ''}
                                       for channel_id in innertube.channel_ids(ids)])

    def import_follows(self, channels):
        """Add new channels and keep known ones; return the number added."""
        with _locked(self.directory):
            entries = self.load('follows')
            known = set(entry['id'] for entry in entries)
            added = [dict(channel, thumbnail=channel.get('thumbnail', ''))
                     for channel in channels if channel['id'] not in known]
            added = added[:max(0, LIMITS['follows'] - len(entries))]
            self._save('follows', entries + added)
        return len(added)


def _in_progress(entry, minimum):
    return (not entry.get('is_live') and entry.get('total')
            and minimum <= entry.get('position', 0) < WATCHED_FRACTION * entry['total'])


def legacy_setting(profile, setting_id):
    """Read a setting value that the settings schema no longer defines."""
    try:
        root = ElementTree.parse(os.path.join(profile, 'settings.xml')).getroot()
    except (OSError, ElementTree.ParseError):
        return ''
    node = root.find("setting[@id='%s']" % setting_id)
    return (node.text or '') if node is not None else ''


def resume_points(history):
    """Resume positions of unfinished videos, keyed by video ID."""
    return dict((entry['id'], (entry['position'], entry['total']))
                for entry in history if _in_progress(entry, 1))


def continue_items(history):
    """Videos with real progress that are not yet watched to the end."""
    return [entry for entry in history if _in_progress(entry, CONTINUE_MIN_SECONDS)]


def recommended(history, fetch_related, sources=3):
    """Interleave the related videos of the newest watched videos."""
    seeds = [entry['id'] for entry in history if not entry.get('is_live')][:sources]
    results, _ = innertube._parallel(fetch_related, seeds)
    watched = set(entry['id'] for entry in history)
    lists = [results[seed] for seed in seeds if seed in results]
    items = []
    for row in range(max([len(related) for related in lists] or [0])):
        for related in lists:
            if row < len(related) and related[row]['id'] not in watched:
                watched.add(related[row]['id'])
                items.append(related[row])
    return items


def parse_takeout_csv(text):
    """Read subscriptions.csv from Google Takeout (YouTube and YouTube Music)."""
    rows = list(csv.reader(io.StringIO(text.lstrip('﻿'))))
    if not rows or [cell.strip() for cell in rows[0][:1]] != ['Channel Id']:
        raise ValueError('Choose subscriptions.csv from Google Takeout')
    channels = []
    seen = set()
    for row in rows[1:]:
        if len(row) < 3 or row[0].strip() in seen:
            continue
        try:
            channel_id, = innertube.channel_ids([row[0].strip()])
        except ValueError:
            continue
        seen.add(channel_id)
        channels.append({'id': channel_id, 'title': row[2].strip()})
    return channels


class Cache(object):
    def __init__(self, directory):
        self.directory = directory

    def prune(self, max_age, now=None):
        """Delete entries older than max_age seconds; the cache only grows otherwise."""
        limit = (time.time() if now is None else now) - max_age
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        for name in names:
            path = os.path.join(self.directory, name)
            try:
                if os.path.getmtime(path) < limit:
                    os.remove(path)
            except OSError:
                continue

    def get(self, key, ttl, fetch, now=None):
        """Return a cached value younger than ttl seconds, else fetch and store it."""
        now = time.time() if now is None else now
        path = os.path.join(self.directory,
                            hashlib.sha1(key.encode('utf-8')).hexdigest() + '.json')
        try:
            with open(path, encoding='utf-8') as handle:
                cached = json.load(handle)
            if now - cached['time'] <= ttl:
                return cached['value']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        value = fetch()
        try:
            _write_json(path, {'time': now, 'value': value})
        except OSError:
            pass  # The cache only saves time; the fetched value is still valid.
        return value
