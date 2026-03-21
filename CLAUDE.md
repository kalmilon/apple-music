# Apple Music Playlist CLI

AI-powered Apple Music playlist management. You recommend songs, then use the CLI to push them to the user's Apple Music library.

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

## Workflow for recommending music

1. User asks for music (a vibe, mood, genre, activity, etc.)
2. You recommend songs as a list of `{artist, title}` objects
3. Run `cli.py match` to batch-find them on Apple Music
4. Review the output:
   - `✓` = good match, use the catalog ID
   - `⚠` = flagged (remix, artist mismatch, DJ mix) — use `cli.py search` to find the right version
   - `✗` = no results
5. Run `cli.py create` with the final list of catalog IDs
6. **MANDATORY: Create the Obsidian listening guide.** Every playlist MUST have a corresponding markdown file. No exceptions. The playlist is not done until the listening guide exists.

### Playlist descriptions and listening guides

Apple Music descriptions don't support line breaks or markdown — everything renders as a single text block. So we split it:

**Apple Music `--description`:** Keep it short — 1-3 sentences. What the playlist is, the vibe, and "Full listening guide in Obsidian."

**Obsidian listening guide:** For every playlist, create a markdown file at `$OBSIDIAN_MUSIC_PATH/<Playlist Name>.md`. The path is set in `.env`. If `OBSIDIAN_MUSIC_PATH` is not set, create guides in `./guides/` within this repo instead.

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
- `cli.py` — CLI with subcommands: match, search, create, list, tracks, add, remove, rename, reorder. Each command does one thing.
- `test_cli.py` — Tests for scoring and matching logic. Run with `uv run pytest test_cli.py`.
- `.env` — contains `APPLE_USER_TOKEN` and `APPLE_STOREFRONT`. `APPLE_DEV_TOKEN` is optional (auto-scraped if not set).

## Token notes

- Dev token: auto-scraped from music.apple.com JS bundle, expires ~every 3 months, no action needed.
- User token: lasts ~6 months. If you get a 401/403, tell the user to refresh it from browser DevTools (media-user-token header on any amp-api request).

## Tech stack

- Python 3.12, uv for dependency management
- `requests` for HTTP, `python-dotenv` for config
- `pytest` for testing (dev dependency)
- No Apple Developer account needed — uses reverse-engineered web player API
