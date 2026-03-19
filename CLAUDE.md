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

### Playlist descriptions and listening guides

Apple Music descriptions don't support line breaks or markdown — everything renders as a single text block. So we split it:

**Apple Music `--description`:** Keep it short — 1-3 sentences. What the playlist is, the vibe, and "Full listening guide in Obsidian."

**Obsidian listening guide:** For every playlist, create a markdown file at:
```
/Users/kalmilon/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault/Music/<Playlist Name>.md
```

The user knows NOTHING about these songs or artists. Write for someone going in completely blind. No jargon. No music-critic speak. Explain everything like a friend who knows music talking over drinks.

The listening guide MUST include:

1. **Header** — playlist name as H1, blockquote with playlist ID, track count, duration, "Don't shuffle"
2. **"What is this?"** — 2-3 sentences. When to listen, what it feels like. Plain language.
3. **"How does it flow?"** — the arc in non-technical terms (e.g. "starts quiet, gets emotional, ends in silence")
4. **Track guide** — H3 per track (numbered), every single one. For each track:
   - **Tagline** — blockquote with emoji, one-line vibe (e.g. `> 🎧 *The one that floats*`)
   - **The feeling** — 2-3 sentences on what you'll experience. Lead with emotion, not analysis.
   - **"Wait for:"** — one specific moment to listen for. Be concrete.
   - **Collapsible context** — use Obsidian callout `> [!info]- The story behind it` (collapsed by default). Inside: who the artist is, why they made this, the social proof (awards, sales, critical reception, who respects them), historical context, anything that makes it hit harder. Break into paragraphs with `>` prefix on each line and `>` for blank lines between paragraphs.
5. **"Before You Press Play"** — bullet list: don't shuffle, use good speakers, it's okay to feel things, expand the story sections for tracks that grab you.

Use `---` dividers between tracks. Keep it scannable — someone should be able to skim the taglines and "wait for" lines and get value, then go deep on anything that hooks them.

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
