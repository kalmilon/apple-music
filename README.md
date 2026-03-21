# Apple Music Playlist CLI

AI recommends songs, CLI pushes them to your Apple Music library as a playlist.

Designed to be used with Claude Code: describe a vibe, get recommendations, run the CLI.

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Get your Apple Music user token

This is the only manual step. It takes 2 minutes and lasts ~6 months.

1. Open https://music.apple.com in Chrome or Safari
2. Sign in to your Apple Music account
3. Open DevTools (`Cmd+Option+I` on Mac, `F12` on Windows)
4. Go to the **Network** tab
5. Click any song or playlist in the web player to trigger a request
6. Look for any request to `amp-api.music.apple.com`
7. Click it, go to **Headers**
8. Copy the value of the `media-user-token` header (long string starting with `0.`)

**That's it.** This is the only token you need. The developer token is auto-scraped from Apple's public JavaScript — no Apple Developer account required.

### 3. Configure your environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
APPLE_USER_TOKEN=<paste your token here>
APPLE_STOREFRONT=us
```

| Variable | Required | Description |
|---|---|---|
| `APPLE_USER_TOKEN` | Yes | Your personal Apple Music session token from step 2 |
| `APPLE_STOREFRONT` | Yes | Two-letter country code for your Apple Music region (`us`, `gb`, `za`, `de`, `jp`, etc.) |
| `APPLE_DEV_TOKEN` | No | Auto-scraped if not set. You never need to touch this. |
| `OBSIDIAN_MUSIC_PATH` | No | Absolute path to a folder for listening guide markdown files. If not set, guides go in `./guides/` |

### 4. Test it

```bash
uv run python cli.py search --query "Miles Davis Blue in Green"
```

If you see results, you're good. If you get a 401/403, your user token is wrong or expired — redo step 2.

## Usage

### With Claude Code

This is the intended way to use it:

```
You: "make me a playlist for a rainy evening"
Claude: recommends 20 songs, creates playlist, writes listening guide
Playlist appears in your Apple Music library.
```

Claude Code knows how to use all the CLI commands. Just ask for music.

### CLI commands

```bash
# Match songs on Apple Music (batch search with scoring)
uv run python cli.py match --songs '[{"artist": "Miles Davis", "title": "Blue in Green"}]'

# Search for a specific song
uv run python cli.py search --query "Miles Davis Blue in Green" --limit 5

# Create a playlist from matched track IDs
uv run python cli.py create --name "Chill Jazz" --track-ids '["123456", "789012"]'

# List your playlists
uv run python cli.py list

# View tracks in a playlist
uv run python cli.py tracks --id p.XXXXX

# Add songs to a playlist
uv run python cli.py add --id p.XXXXX --track-ids '["123456"]'

# Remove songs from a playlist
uv run python cli.py remove --id p.XXXXX --track-ids '["i.XXXXX"]'

# Rename or redescribe a playlist
uv run python cli.py rename --id p.XXXXX --name "New Name" --description "..."

# Reorder a playlist (creates new playlist in order, deletes old)
uv run python cli.py reorder --id p.XXXXX --track-ids '["catalog-id-1", "catalog-id-2"]'
```

## Security

- **`.env` is gitignored.** Your tokens never leave your machine.
- **User tokens are personal.** Each person needs their own token from their own Apple Music account. Do not share user tokens.
- **Dev token is public.** It's scraped from Apple's public JavaScript. Everyone gets the same one. It's safe to share but there's no need — it's auto-scraped.
- **No Apple Developer account needed.** This uses the reverse-engineered web player API. See [technical-primer.md](technical-primer.md) for details.

## Token lifecycle

| Token | How to get | Lifespan | When it expires |
|---|---|---|---|
| Dev token | Auto-scraped (no action needed) | ~3 months | Silently refreshed next run |
| User token | Copy from browser DevTools | ~6 months | CLI will print clear instructions to refresh |

## How it works

1. `match` searches each song against Apple Music's catalog, scores candidates (penalizing remixes, DJ mixes, wrong artists), and returns the best catalog IDs with warnings for anything suspicious
2. You review the output — fix any flagged tracks with `search`
3. `create` builds the playlist from the final list of catalog IDs
4. `add`, `remove`, `rename`, `reorder` for ongoing management

See [technical-primer.md](technical-primer.md) for full details on the reverse-engineered API.
