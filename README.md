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
# Create a playlist
uv run python cli.py create --name "Chill Jazz" --songs '[{"artist": "Miles Davis", "title": "Blue in Green"}]'

# List your playlists
uv run python cli.py list

# View tracks in a playlist
uv run python cli.py tracks --id p.XXXXX

# Update a playlist (metadata, add/remove tracks — all in one)
uv run python cli.py update --id p.XXXXX --name "New Name" --description "..."
uv run python cli.py update --id p.XXXXX --add-songs '[{"artist": "...", "title": "..."}]'
uv run python cli.py update --id p.XXXXX --remove-track-ids '["i.XXXXX"]' --add-track-ids '["1234567"]'

# Rebuild a playlist in a new order (creates new playlist, deletes old)
uv run python cli.py rebuild --id p.XXXXX --track-ids '["catalog-id-1", "catalog-id-2"]'

# Search Apple Music catalog
uv run python cli.py search --query "Miles Davis Blue in Green" --limit 5
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

1. Songs are searched against the Apple Music catalog via the web player API
2. Matched tracks are collected by catalog ID
3. A new playlist is created in your library
4. Tracks are added to the playlist

See [technical-primer.md](technical-primer.md) for full details on the reverse-engineered API.
