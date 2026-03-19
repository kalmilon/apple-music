# Apple Music Playlist CLI

AI-powered Apple Music playlist management. You recommend songs, then use the CLI to push them to the user's Apple Music library.

## How to use the CLI

All commands run with `uv run python cli.py <command>`.

### Create a playlist
```bash
uv run python cli.py create --name "Playlist Name" --description "description" --songs '[{"artist": "Miles Davis", "title": "Blue in Green"}]'
```

### List playlists
```bash
uv run python cli.py list
```

### View tracks in a playlist
```bash
uv run python cli.py tracks --id p.XXXXX
```

### Update playlist metadata
```bash
uv run python cli.py update --id p.XXXXX --name "New Name" --description "New description"
```

### Add songs to an existing playlist
```bash
uv run python cli.py add --id p.XXXXX --songs '[{"artist": "Artist", "title": "Song"}]'
```

### Remove tracks from a playlist
```bash
uv run python cli.py remove --id p.XXXXX --track-ids '["i.XXXXX"]'
```
Note: track IDs for removal are library-song IDs (start with `i.`), not catalog IDs. Get them from `cli.py tracks`.

### Search Apple Music catalog
```bash
uv run python cli.py search --query "Miles Davis Blue in Green" --limit 5
```

## Workflow for recommending music

1. User asks for music (a vibe, mood, genre, activity, etc.)
2. You recommend songs as a list of `{artist, title}` objects
3. Use `cli.py create` to push the playlist, or `cli.py add` to append to an existing one
4. If search picks the wrong version (remix, cover, live), use `cli.py search` to find the right one, then `cli.py remove` the wrong track and `cli.py add` the correct one

### Picking the right version

`search_song` returns top 3 results with metadata: album, release date, duration, audio traits (lossless/hi-res), ISRC. Use this to pick the best version:
- Prefer original album releases over compilations
- Prefer the original artist over covers
- Prefer lossless/hi-res audio traits when available
- Avoid remixes unless specifically requested

## Architecture

- `apple_music.py` — API client. Talks to `amp-api.music.apple.com` (Apple Music web player's internal API). Two tokens: dev token (auto-scraped from Apple's JS bundle) and user token (from `.env`).
- `cli.py` — CLI with subcommands: create, list, tracks, update, add, remove, search.
- `.env` — contains `APPLE_USER_TOKEN` and `APPLE_STOREFRONT`. `APPLE_DEV_TOKEN` is optional (auto-scraped if not set).

## Token notes

- Dev token: auto-scraped from music.apple.com JS bundle, expires ~every 3 months, no action needed.
- User token: lasts ~6 months. If you get a 401/403, tell the user to refresh it from browser DevTools (media-user-token header on any amp-api request).

## Tech stack

- Python 3.12, uv for dependency management
- `requests` for HTTP, `python-dotenv` for config
- No Apple Developer account needed — uses reverse-engineered web player API
