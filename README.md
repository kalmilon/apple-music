# Apple Music Playlist CLI

AI recommends songs, CLI pushes them to your Apple Music library as a playlist.

Designed to be used with Claude Code: describe a vibe, get recommendations, run the CLI.

## Setup

```bash
uv sync
```

### Get your Apple Music user token (one-time, lasts ~6 months)

1. Open https://music.apple.com and sign in
2. Open DevTools (`Cmd+Option+I`) > Network tab
3. Click any song or playlist to trigger a request
4. Find a request to `amp-api.music.apple.com`
5. Copy the `media-user-token` header value

### Configure

Create a `.env` file:

```
APPLE_USER_TOKEN=<your token from above>
APPLE_STOREFRONT=za
```

The developer token is auto-scraped from Apple's web player. No Apple Developer account needed.

## Usage

```bash
uv run python cli.py --name "Chill Jazz" --songs '[
  {"artist": "Miles Davis", "title": "Blue in Green"},
  {"artist": "John Coltrane", "title": "Naima"}
]'
```

Or pipe from stdin:

```bash
echo '<json>' | uv run python cli.py --name "My Playlist"
```

### With Claude Code

```
You: "make me a playlist for a rainy evening"
Claude: recommends 20 songs, runs cli.py
Playlist appears in your Apple Music library.
```

## How it works

1. Songs are searched against the Apple Music catalog via the web player API
2. Matched tracks are collected by catalog ID
3. A new playlist is created in your library
4. Tracks are added to the playlist

See [technical-primer.md](technical-primer.md) for details on the reverse-engineered API.
