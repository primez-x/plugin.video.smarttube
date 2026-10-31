# SmartTube for Kodi (`plugin.video.smarttube`)

YouTube for Kodi without the bloat — and without API keys. Search, browse the
home feed, channels and playlists, and play videos signed out, on every Kodi
platform (Windows, Linux, CoreELEC/LibreELEC, Android, macOS). This is an
unofficial, Kodi-native reimplementation of the SmartTube idea in Python; it
is not the Android SmartTube app and shares no code with it.

## What works

- **No setup.** No Google Cloud project, no personal API key, no sign-in.
  Listings use YouTube's public InnerTube WEB client; playback uses the same
  signed-out player clients (testsuite-params, then VR) that the classic
  YouTube add-on defaults to. SmartTube writes a DASH manifest from the
  separate audio and video files and plays the manifest with InputStream
  Adaptive: VP9 up to 4K60, VP9.2 HDR when the display reports HDR and the
  HDR video setting allows HDR (Auto: Kodi 22 or later, because Kodi 21 shows
  add-on HDR streams as SDR; On: a Kodi 21 build with xbmc commit 085c4d3,
  such as p3i firmware from 2026-10-30), H.264
  for videos without VP9, and AAC audio (with a set per dubbed language).
  AV1 is not used. Live videos play from YouTube's HLS manifest; the best
  progressive file is the last fallback.
- **SponsorBlock.** A background service seeks past sponsored and other
  crowd-sourced segments. Each category group can be toggled in settings.
- **DeArrow.** Clickbait titles and thumbnails in listings are replaced with
  crowd-sourced alternatives (toggleable).
- **Return YouTube Dislike** (optional, off by default): like/dislike counts
  on the playing item's info.
- **Drop-in URLs.** The search and play URL shapes of `plugin.video.youtube`
  are accepted unchanged apart from the add-on id, so Starlight search
  and info rows and the PlexKodiConnect YouTube player repoint with a plain
  `plugin.video.youtube` → `plugin.video.smarttube` substitution:

  ```
  plugin://plugin.video.smarttube/search/?q=<QUERY>
  plugin://plugin.video.smarttube/kodion/search/query/?q=<QUERY>&search_type=notvalid
  plugin://plugin.video.smarttube/play/?video_id=<VIDEO_ID>
  plugin://plugin.video.smarttube/channel/<CHANNEL_ID>
  plugin://plugin.video.smarttube/playlist/<PLAYLIST_ID>
  ```

## Starlight routes (v0.2.0)

- `plugin://plugin.video.smarttube/trailer?title=<TITLE>&year=<YEAR>` plays the highest-ranked trailer.
- Add `mode=lookup` for a playable trailer row without automatic playback.
- Optional trailer parameters: `imdb`, `tmdb`, and `media_type=movie|tv`.
  IDs are accepted for caller context; YouTube search uses the title and year.
- `plugin://plugin.video.smarttube/live_now` lists current streams from local follows.
  Follow or unfollow a channel from a channel or video context menu.
- Supply `channel_ids=<UC_ID>,<UC_ID>` to merge an external subscription list with local follows.
  No Google account sync is available. The combined list supports up to 200 channels.
- Live rows play through `/play/?channel_id=<UC_ID>&live=1` and recheck the current stream.
  Each channel scan reads at most three result pages. Scheduled streams stay excluded.
- Rows expose `Starlight.Source=YouTube`, `IsLive`, `Starlight.IsLive`, and `IsPlayable`.
  Available thumbnails also populate `thumb`, `icon`, `landscape`, and `fanart`.
- No M3U or XMLTV export is available. YouTube provides no reliable programme schedule through the current client.

## App sections (v0.3.0)

The main menu, skin hubs and widgets share these folders:

| Section | Path | Source |
| --- | --- | --- |
| Subscriptions | `/subscriptions/` | Latest uploads of followed channels (channel RSS feeds, Shorts excluded) |
| Continue watching | `/continue/` | Unfinished videos from the local history |
| Recommended | `/recommended/` | Related videos of the three newest watched videos; Trending until the history has entries |
| Trending | `/trending/` | YouTube Charts "Trending" list for the region setting |
| Live now | `/live_now` | Current streams of followed channels |
| History | `/history/` | Videos played from SmartTube lists |
| Watch later | `/watch_later/` | Local list |
| Channels | `/channels/` | Followed channels, plus the Google Takeout import |
| Playlists | `/playlists/` | Saved YouTube playlists |
| Search | `/search/` | New search and the search history |
| Categories | `/explore/<music, gaming, news, sports, live, learning, fashion>/` | YouTube category pages |

All paths start with `plugin://plugin.video.smarttube`. `/related/?video_id=<ID>`
lists the related videos of one video.

- **Local library.** Subscriptions, history, Watch later, saved playlists and
  search history are JSON files in the add-on profile. Context menus change
  them. Settings → Library clears the history lists.
- **Subscriptions without sign-in.** Follow channels from a channel or video
  context menu, or import `subscriptions.csv` from Google Takeout
  (Settings → Library, or the first row of Channels). The list holds up to
  200 channels.
- **History.** Only videos played from SmartTube lists enter the history.
  Trailers and `play/?video_id=` links from skins and other add-ons stay out.
  The service saves the position every 30 seconds and when playback stops.
- **Trending.** YouTube retired its general Trending page in July 2025.
  The Trending section shows the YouTube Charts trending list instead, which
  is mostly music.
- **Signed-out Home.** YouTube returns an empty Home feed without a watch
  history, so SmartTube shows Recommended in place of Home.

## Not included yet

- Google account sync: account subscriptions, watch history, likes,
  comments and account playlists. YouTube blocks sign-in for TV-style
  clients, so SmartTube keeps these lists on the device.
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
refreshed or the trailer paths are rewritten. Starlight and PlexKodiConnect search,
info and player links are repointed in those add-ons instead.

## Development

```bash
python3 -m unittest discover -s tests
git config core.hooksPath .githooks
```

`innertube.py`, `dash.py`, `extras.py`, `library.py` and `routes.py` are pure standard-library Python
and are fully covered without Kodi or network access; `plugin.py` and
`service.py` are thin Kodi adapters. Versioning and publishing follow
`VERSIONING.md` in `primez-x/kodi.addons` (see `AGENTS.md`).

SponsorBlock and DeArrow data are CC BY-NC-SA 4.0 (sponsor.ajay.app /
dearrow.ajay.app). This add-on is GPL-2.0-only; see `LICENSES/`.
