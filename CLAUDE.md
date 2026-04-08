# Apple Music Playlist CLI

AI-powered Apple Music playlist management. You recommend songs, then use the CLI to push them to the user's Apple Music library.

**IMPORTANT: Never create, modify, or delete playlists without explicit user approval. Propose first, wait for a clear "yes" / "go ahead" / approval before running create, add, remove, reorder, or rename commands.**

**Experimental playlists:** Tryout/proposed playlists use a ` [Experimental]` suffix (e.g. "The Highway Dissolves [Experimental]"). This marks them as disposable — easy to identify, keep, or delete. When the user says "make experimental stuff" or "delete the experimental ones", this is what they mean.

**Always include fresh discoveries:** When building playlists, use web search to find recent releases, new artists, and tracks from the last 1-2 years in the relevant genre. Don't rely solely on existing knowledge — mix well-known picks with genuinely new stuff.

## How to use the CLI

All commands run with `uv run python cli.py <command>`.

### Match songs on Apple Music
```bash
uv run python cli.py match --songs '[{"artist": "Miles Davis", "title": "Blue in Green"}, {"artist": "Daft Punk", "title": "One More Time"}]'
```
Batch searches Apple Music, scores results, and flags problems (artist mismatches, remixes, DJ mix versions). Outputs catalog IDs you can pass to `create` or `add`. Always run this before creating a playlist — review the output and fix any flagged tracks with `search` before proceeding.

### Search Apple Music catalog
```bash
uv run python cli.py search --query "Miles Davis Blue in Green" --limit 5
```
One-off lookup. Use this to find the right version when `match` flags a problem.

### Create a playlist
```bash
uv run python cli.py create --name "Playlist Name" --description "description" --track-ids '["123", "456"]'
uv run python cli.py create --name "Playlist Name" --track-ids '["123"]' --upsert  # adds to existing if name matches
```
Takes catalog IDs (from `match` or `search`). Does not do any searching — expects pre-resolved IDs.

### List playlists
```bash
uv run python cli.py list
```

### View tracks in a playlist
```bash
uv run python cli.py tracks --id p.XXXXX
```

### Add songs to a playlist
```bash
uv run python cli.py add --id p.XXXXX --track-ids '["1234567", "2345678"]'
```

### Remove songs from a playlist
```bash
uv run python cli.py remove --id p.XXXXX --track-ids '["i.XXXXX", "i.YYYYY"]'
```
Uses library-song IDs (the `i.XXX` IDs from `tracks` output).

### Rename or redescribe a playlist
```bash
uv run python cli.py rename --id p.XXXXX --name "New Name" --description "New desc"
```

### Reorder a playlist
```bash
uv run python cli.py reorder --id p.XXXXX --track-ids '["catalog-id-1", "catalog-id-2", ...]'
```
Creates a new playlist with the same name/description, adds tracks in the specified order, deletes the old one. Returns the new playlist ID. Use this when you need to resequence tracks (the API has no insert-at-position).

### Search YouTube
```bash
uv run python cli.py yt-search --query "persona 5 cafe music" --limit 5
```
Searches YouTube and displays results with clickable links and durations. Use this to find audio (ambient mixes, game soundtracks, live performances, etc.) that isn't on Apple Music's catalog.

### Download from YouTube into Music.app
```bash
uv run python cli.py yt-download --url "https://youtube.com/watch?v=..." --name "Cafe Leblanc"
```
Downloads audio as m4a via yt-dlp and imports it into Music.app (shows up in Recently Added, syncs via iCloud Music Library). Use `--name` to set a clean filename (default: video title, sanitized). Use `--no-import` to download without importing. Files are saved to `~/Music/YouTube Downloads/`.

Automatically tags metadata before importing:
- **Title** → `--name` or video title
- **Artist** → `--artist` or YouTube channel name
- **Album** → `--album` or "YouTube"
- **Artwork** → YouTube thumbnail embedded as cover art

## Workflow for YouTube downloads

1. User asks for something that's not on Apple Music (game OSTs, ambient mixes, live sets, etc.)
2. Run `cli.py yt-search` to find it on YouTube, show the user the results with links
3. User clicks links, listens, confirms which one(s) they want
4. Run `cli.py yt-download` for each confirmed video — downloads and imports into Music.app

## Workflow for recommending music

1. User asks for music (a vibe, mood, genre, activity, etc.)
2. You recommend songs as a list of `{artist, title}` objects
3. Run `cli.py match` to batch-find them on Apple Music
4. Review the output:
   - `✓` = good match, use the catalog ID
   - `⚠` = flagged (remix, artist mismatch, DJ mix) — use `cli.py search` to find the right version
   - `✗` = no results
5. Run `cli.py create` with the final list of catalog IDs
6. **Optional: Create an Obsidian listening guide** if the user asks for one, or for playlists that are being kept (not experimental). Not every playlist needs one.

### Playlist descriptions and listening guides

Apple Music descriptions don't support line breaks or markdown — everything renders as a single text block. Make the description count — it's the only context the user sees in Apple Music.

**Apple Music `--description`:** 3-5 sentences. Describe the vibe, the arc, what kind of listening it's for, and name-drop a few key artists or moments. Give enough detail that someone browsing their library remembers what this playlist is about.

**Obsidian listening guide (optional):** When requested, create a markdown file at `$OBSIDIAN_MUSIC_PATH/<Playlist Name>.md`. The path is set in `.env`. If `OBSIDIAN_MUSIC_PATH` is not set, create guides in `./guides/` within this repo instead.

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

### How match scoring works

`match` searches Apple Music with a higher limit (10 results) and scores each candidate:
- **Artist match** (+25): all significant words from the requested artist appear in the result artist
- **Remix/mix penalty** (-25): track name contains Remix, Mixed, Rework, Sped Up, etc. (unless the user requested a remix)
- **DJ mix/compilation penalty** (-15): album name contains DJ Mix, Ministry of Sound, fabric, Ibiza, etc.
- **Audio quality boost** (+1 to +5): lossless, hi-res, Atmos, spatial

Remasters and radio edits are NOT penalized — they're treated as valid original versions.

## Architecture

- `apple_music.py` — API client. Talks to `amp-api.music.apple.com` (Apple Music web player's internal API). Two tokens: dev token (auto-scraped from Apple's JS bundle) and user token (from `.env`).
- `cli.py` — CLI with subcommands: match, search, create, list, tracks, add, remove, rename, reorder, yt-search, yt-download. Each command does one thing.
- `test_cli.py` — Tests for scoring and matching logic. Run with `uv run pytest test_cli.py`.
- `.env` — contains `APPLE_USER_TOKEN` and `APPLE_STOREFRONT`. `APPLE_DEV_TOKEN` is optional (auto-scraped if not set).

## Rate limiting

The Apple Music search API rate-limits at roughly ~20 req/s, ~300 req/min sustained. The penalty window is a rolling period — mild overages clear in minutes, heavy bursts (80+ requests) can lock you out for 10+ minutes. No `Retry-After` header is returned. Only the search endpoint is affected; library endpoints (list, tracks, create, add) are separate.

**Built-in protections:**
- `apple_music.py` throttles all requests to 300ms apart (~3.3 req/s)
- 429s trigger exponential backoff: 4s, 8s, 16s, 32s (starts high to avoid extending the penalty)
- `cli.py` caches search results in `.search_cache/` — same query never hits the API twice

**CRITICAL: Never run multiple `match` commands in parallel.** Each process has its own throttle with no cross-process coordination. 4 parallel matches = 4x the request rate, guaranteed 429. Either combine all songs into one `match` call, or run them sequentially. This is the #1 cause of rate limit disasters.

**When rate limited:** Stop making requests — every retry extends the penalty. Wait 5-10 minutes before trying again.

## Token notes

- Dev token: auto-scraped from music.apple.com JS bundle, expires ~every 3 months, no action needed.
- User token: lasts ~6 months. If you get a 401/403, tell the user to refresh it from browser DevTools (media-user-token header on any amp-api request).

## Tech stack

- Python 3.12, uv for dependency management
- `requests` for HTTP, `python-dotenv` for config
- `pytest` for testing (dev dependency)
- No Apple Developer account needed — uses reverse-engineered web player API
