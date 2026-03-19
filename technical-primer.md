# Technical Primer: Apple Music Web API

How this project interacts with Apple Music without an Apple Developer account.

## The official way (and why we skip it)

Apple's MusicKit API requires enrollment in the Apple Developer Program ($99/yr). You generate a private key, sign a JWT developer token, and use their SDK. This is how every B2C app (SongShift, Playlist AI, Tune My Music) does it.

We don't do this.

## What we do instead

Apple's web player at `music.apple.com` is itself an API client. It authenticates with the same backend API that MusicKit uses. We use its credentials.

### Two-token system

Every Apple Music API request needs two tokens:

| Token | What it does | How we get it | Lifespan |
|---|---|---|---|
| **Developer token** | Identifies the app | Scraped from the web player's JavaScript bundle | ~3 months |
| **User token** | Authenticates your account | Manually copied from browser DevTools | ~6 months |

### Developer token (auto-scraped)

The web player embeds a JWT developer token in its JS bundle. It's publicly accessible — no login required.

```
GET https://music.apple.com
→ parse HTML for /assets/*.js URLs
→ fetch each JS file
→ regex for JWT: eyJh[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+
```

The token is a standard JWT (ES256):

```json
{
  "alg": "ES256",
  "typ": "JWT",
  "kid": "WebPlayKid"
}
{
  "iss": "AMPWebPlay",
  "iat": 1772063156,
  "exp": 1779320756,
  "root_https_origin": ["apple.com"]
}
```

Issuer is `AMPWebPlay` (Apple Music Player Web Play). Apple rotates this periodically.

### User token (manual)

The user token is an opaque session token (not a JWT). It's created when you sign in to `music.apple.com` via Apple's `postMessage`-based auth popup (not standard OAuth). It appears as the `media-user-token` cookie and the `Music-User-Token` request header.

No programmatic way to obtain this without a browser session. The user copies it once from DevTools.

## API endpoints

Base URL: `https://amp-api.music.apple.com`

This is the internal API used by the web player. Same data as the official `api.music.apple.com`, slightly different capabilities.

### Headers (all requests)

```
Authorization: Bearer <developer_token>
Music-User-Token: <user_token>
Origin: https://music.apple.com
```

### Search catalog

```
GET /v1/catalog/{storefront}/search?term={query}&types=songs&limit=1
```

Returns catalog song objects with `id`, `attributes.name`, `attributes.artistName`, `attributes.albumName`. The `id` is a numeric string (e.g. `"1596494903"`) used to reference the track in other calls.

Storefront is a two-letter country code (`us`, `za`, `gb`, etc.) that determines which catalog to search.

### Create playlist

```
POST /v1/me/library/playlists

{
  "attributes": {
    "name": "My Playlist",
    "description": "Optional description"
  },
  "relationships": {
    "tracks": {"data": []}
  }
}
```

Returns the created playlist object. The `id` is a string like `p.DV7rOmahRQVz7QZ`.

### Add tracks to playlist

```
POST /v1/me/library/playlists/{playlist_id}/tracks

{
  "data": [
    {"id": "1596494903", "type": "songs"},
    {"id": "1440857781", "type": "songs"}
  ]
}
```

Returns 200/201 on success. Tracks are appended — calling this multiple times adds more tracks.

## Error handling

| Status | Meaning | Action |
|---|---|---|
| 200/201/204 | Success | — |
| 401/403 | Token expired or invalid | Re-scrape dev token / refresh user token |
| 429 | Rate limited | Back off and retry |

## Risks and limitations

- **Apple can break this at any time** by changing the JS bundle structure or API endpoints. This is reverse-engineered, not contracted.
- **No token refresh** for the user token. When it expires (~6 months), you manually grab a new one.
- **Rate limits** exist but are generous for personal use. The web player itself makes hundreds of requests per session.
- **Storefront matters.** Searching `za` (South Africa) may return different results than `us`. Some tracks are region-locked.

## Prior art

- [Myp3a/apple-music-api](https://github.com/Myp3a/apple-music-api) — Python wrapper, similar approach, includes DRM decryption
- [Cider](https://github.com/ciderapp/Cider) — Open-source Apple Music desktop client
- [passport-apple-music](https://www.npmjs.com/package/passport-apple-music) — Reverse-engineered MusicKit JS auth for PassportJS
