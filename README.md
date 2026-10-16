# SmartTube for Kodi (`plugin.video.smarttube`)

YouTube for Kodi without the bloat — and without API keys. Search, browse the
home feed, channels and playlists, and play videos signed out, on every Kodi
platform (Windows, Linux, CoreELEC/LibreELEC, Android, macOS). This is an
unofficial, Kodi-native reimplementation of the SmartTube idea in Python; it
is not the Android SmartTube app and shares no code with it.

## What works in v0.1.0

- **No setup.** No Google Cloud project, no personal API key, no sign-in.
  Listings use YouTube's public InnerTube WEB client; playback uses the same
  signed-out player clients (testsuite-params, then VR) that the classic
  YouTube add-on defaults to, preferring DASH/HLS manifests via
  InputStream Adaptive and falling back to the best progressive file.
- **SponsorBlock.** A background service seeks past sponsored and other
  crowd-sourced segments. Each category group can be toggled in settings.
- **DeArrow.** Clickbait titles and thumbnails in listings are replaced with
  crowd-sourced alternatives (toggleable).
- **Return YouTube Dislike** (optional, off by default): like/dislike counts
  on the playing item's info.
- **Drop-in URLs.** The search and play URL shapes of `plugin.video.youtube`
  are accepted unchanged apart from the add-on id, so Arctic Fuse 3 search
  and info rows and the TMDb Helper YouTube player repoint with a plain
  `plugin.video.youtube` → `plugin.video.smarttube` substitution:

  ```
  plugin://plugin.video.smarttube/search/?q=<QUERY>
  plugin://plugin.video.smarttube/kodion/search/query/?q=<QUERY>&search_type=notvalid
  plugin://plugin.video.smarttube/play/?video_id=<VIDEO_ID>
  plugin://plugin.video.smarttube/channel/<CHANNEL_ID>
  plugin://plugin.video.smarttube/playlist/<PLAYLIST_ID>
  ```

## Not included yet

- Signed-in features: subscriptions feed, watch history sync, likes,
  comments and account playlists. Anonymous browsing and playback need none
  of these; TV device-code sign-in is planned as an optional extra.
- Adaptive DASH in the rare case where YouTube returns neither a DASH nor an
  HLS manifest URL: playback then falls back to the best progressive file
  (typically up to 720p). Generating an MPD from adaptive formats, as the
  classic add-on does, is future work.
- YouTube changes its player clients regularly. When playback breaks for
  everyone, the fix is a client version bump in `resources/lib/innertube.py`
  (`CLIENTS` / `PLAYER_CLIENT_ORDER`), released as a patch version.

## Install

Install from the Primez Kodi repository (`repository.primez.addons`), which
also delivers updates. InputStream Adaptive must be enabled (Settings →
Player, or it is installed automatically as a dependency on most platforms).

Existing library trailer fields that still contain
`plugin://plugin.video.youtube/...` URLs are database values, not skin
links; they keep pointing at the old add-on until the affected titles are
refreshed or the trailer paths are rewritten. Skin and TMDb Helper search,
info and player links are repointed in those add-ons instead.

## Development

```bash
python3 -m unittest discover -s tests
git config core.hooksPath .githooks
```

`innertube.py`, `extras.py` and `routes.py` are pure standard-library Python
and are fully covered without Kodi or network access; `plugin.py` and
`service.py` are thin Kodi adapters. Versioning and publishing follow
`VERSIONING.md` in `primez-x/kodi.addons` (see `AGENTS.md`).

SponsorBlock and DeArrow data are CC BY-NC-SA 4.0 (sponsor.ajay.app /
dearrow.ajay.app). This add-on is GPL-2.0-only; see `LICENSES/`.
