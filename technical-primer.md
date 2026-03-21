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

---

# Technical Primer: Lossless Download Pipeline

How this project downloads and decrypts lossless audio from Apple Music.

## The problem: FairPlay DRM

Apple Music streams are encrypted with FairPlay DRM (CBCS mode). On iOS, decryption happens in a hardware secure enclave — inaccessible to software. On Mac, it's locked inside system frameworks. You can stream and listen, but you never touch an unencrypted file.

The crack: Apple ships an Android app. Android is open — you can root it, inject code into running processes, and intercept the decryption as it happens. The app's native library (`libandroidappmusic.so`) contains the FairPlay decryption implementation. A tool called Frida hooks into three functions — `getPersistentKey()`, `decryptContext()`, `decryptSample()` — and captures the decrypted output.

We don't run Frida ourselves. We connect to a remote service that does.

## Architecture: three layers

```
┌─────────────┐     gRPC/TLS      ┌──────────────────┐     TCP      ┌─────────┐
│  Our CLI    │ ◄──────────────► │ wrapper-manager  │ ◄──────────► │ wrapper │
│  (Python)   │                   │ (Go)             │              │ (C)     │
└─────────────┘                   └──────────────────┘              └─────────┘
      │                                    │                             │
      │ Downloads encrypted                │ Routes requests             │ Runs Apple Music
      │ audio from Apple CDN               │ across accounts/            │ Android app's native
      │                                    │ regions                     │ decryption libraries
      │ Reassembles, tags                  │                             │ in a chroot
      ▼                                    ▼                             ▼
  .m4a file                        Multiple Apple Music          libandroidappmusic.so
                                   accounts (US, JP, etc.)       libstoreservicescore.so
```

**Wrapper** (C, [WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper)) — Runs the Android app's `.so` files directly on Linux x86_64/arm64 via chroot + Android's linker64. No emulator needed. Exposes three TCP ports: decrypt (10020), M3U8 (20020), account login (30020).

**Wrapper-manager** (Go, [WorldObservationLog/wrapper-manager](https://github.com/WorldObservationLog/wrapper-manager)) — Orchestrates multiple wrapper instances, each logged in with a different Apple Music account in a different region. Exposes a unified gRPC API. Routes decryption requests to the right instance based on region availability.

**Our CLI** (Python) — The client. Talks to the wrapper-manager over gRPC. Handles everything else: metadata, download, sample extraction, reassembly, tagging.

Public wrapper-manager instances: `wm.wol.moe` (project author), `wm1.wol.moe` (contributor). No setup required — just connect.

## gRPC protocol

We use Protocol Buffers over gRPC (HTTP/2). The proto definition comes from wrapper-manager's `proto/manager.proto`.

### Key RPCs

| RPC | Type | Purpose |
|-----|------|---------|
| `Status` | Unary | Check if service is ready, list available regions |
| `M3U8` | Unary | Get HLS manifest for a song (requires authenticated session) |
| `Decrypt` | Bidirectional stream | Send encrypted samples, receive decrypted bytes |
| `Login` | Bidirectional stream | Authenticate an Apple ID (with 2FA support) |

### The Decrypt stream

This is the critical RPC. It's bidirectional streaming — both client and server send messages concurrently on a single connection.

```protobuf
rpc Decrypt (stream DecryptRequest) returns (stream DecryptReply);

message DecryptData {
  string adam_id = 1;      // Apple's song ID (e.g. "268443092")
  string key = 2;          // FairPlay key URI (skd://...)
  int32 sample_index = 3;  // Position in sample list
  bytes sample = 4;        // Raw encrypted/decrypted bytes
}
```

The client opens one stream and pushes all encrypted samples through it. The server decrypts each one and streams back the results. A keepalive message (`adam_id="KEEPALIVE"`) is sent every 15 seconds to prevent timeout.

Our implementation uses threading: one thread reads responses, the main thread writes requests. Failed samples are retried up to 3 times.

## The download pipeline

### Step 1: Metadata

```
GET https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{adam_id}
```

Standard catalog API call. Returns title, artist, album, artwork URL, track number, ISRC, genre, etc. Same API the playlist commands use.

### Step 2: M3U8 (HLS manifest)

The wrapper-manager's `M3U8` RPC returns the HLS master playlist for a song. This requires an authenticated Apple Music session — the wrapper-manager uses one of its logged-in accounts.

The master M3U8 contains multiple `#EXT-X-MEDIA` entries, each representing a different audio format:

| Group ID pattern | Format | Quality |
|-----------------|--------|---------|
| `audio-alac-stereo-44100-16` | ALAC | 16-bit/44.1kHz (CD quality) |
| `audio-alac-stereo-48000-24` | ALAC | 24-bit/48kHz (Hi-Res) |
| `audio-alac-stereo-96000-24` | ALAC | 24-bit/96kHz (Hi-Res) |
| `audio-alac-stereo-192000-24` | ALAC | 24-bit/192kHz (Hi-Res) |
| `audio-stereo-256` | AAC | 256kbps |
| `audio-atmos-2048` / `audio-ec3-2048` | Dolby Atmos | EC-3 |

We parse with the `m3u8` Python library, match against codec regex patterns, and pick the best available stream.

### Step 3: Variant playlist and keys

Each media entry's URI points to a variant M3U8 (second-level playlist). This contains:

- **`#EXT-X-MAP:URI="..."`** — URL to the actual encrypted audio file (single fragmented MP4 on Apple's CDN)
- **`#EXT-X-KEY:URI="skd://..."`** — FairPlay Streaming key URIs

Key URIs are suffixed by codec:
- `c23` = ALAC
- `c22` = AAC
- `c24` = Atmos (EC-3/AC-3)

A prefetch key (`skd://itunes.apple.com/P000000000/s1/e1`) is always prepended to the key list.

### Step 4: Download encrypted audio

```
GET https://aod.itunes.apple.com/itunes-assets/...
```

The encrypted file is a fragmented MP4 (fMP4) on Apple's CDN. It's publicly accessible — the URL has auth tokens baked in. The content is CBCS-encrypted and completely unplayable without decryption keys.

### Step 5: Extract samples

This is the most complex step. We need to split the fMP4 into individual encrypted samples to send to the wrapper-manager one at a time.

**Tools used:**

1. **gpac** — `gpac -i raw.mp4 nhmlw:pckp=true -o raw.nhml`

   Produces two files:
   - `raw.nhml` — XML listing every sample with offset, length, and duration
   - `raw.media` — raw concatenated sample bytes

2. **MP4Box** — `MP4Box -diso raw.mp4 -out raw.xml`

   Dumps the full ISO box structure as XML. We parse `MovieFragmentBox` → `TrackFragmentHeaderBox` → `SampleDescriptionIndex` to know which FairPlay key each sample needs.

3. **mp4extract** (Bento4) — `mp4extract moov/trak/mdia/minf/stbl/stsd/enca[0]/alac raw.mp4 alac.atom`

   Extracts the ALAC decoder parameters atom. Needed later to make the output file playable.

**What an MP4 looks like inside:**

```
fMP4 file
├── moov (movie metadata)
│   └── trak → stsd → enca (encrypted audio sample entry)
│       └── alac (decoder params)    ← we extract this
├── moof (movie fragment 1)          ← SampleDescriptionIndex tells us which key
│   └── mdat (encrypted samples)
├── moof (movie fragment 2)
│   └── mdat (encrypted samples)
└── ...
```

Each `moof`/`mdat` pair contains a fragment of audio. Each fragment has a `SampleDescriptionIndex` that maps to a key URI from step 3. A typical 4-minute song has ~1000 samples.

### Step 6: Decrypt

Open a bidirectional gRPC stream. For each sample, send:
- `adam_id` — the song's catalog ID
- `key` — the `skd://` URI (selected by `SampleDescriptionIndex`)
- `sample_index` — position (so we can reassemble in order)
- `sample` — the raw encrypted bytes

The wrapper-manager routes each sample to a wrapper instance, which runs it through `libandroidappmusic.so` and returns the decrypted bytes. Takes a few seconds for a full song.

If a sample fails, we retry up to 3 times before giving up.

### Step 7: Reassemble

The reverse of step 5. We take the decrypted sample bytes and build a playable .m4a file.

**For ALAC:**

1. Write decrypted bytes to `dec.media`
2. Rewrite NHML XML: update `baseMediaFile` to point to decrypted media, change `mediaSubType` from `enca` to `alac`
3. `gpac -i dec.nhml nhmlr -o dec.m4a` — re-mux samples into M4A
4. `mp4edit --insert moov/trak/mdia/minf/stbl/stsd/alac:alac.atom dec.m4a out.m4a` — insert ALAC decoder params
5. `MP4Box -brand "M4A " -ab "M4A " -ab "mp42" out.m4a` — set file brand
6. `ffmpeg -y -i out.m4a -fflags +bitexact -c:a copy final.m4a` — fix metadata quirks

**For Atmos (EC-3):**

Simpler — `gpac -i dec.media -o dec.m4a` (direct remux, no NHML round-trip), then the same MP4Box/ffmpeg steps.

### Step 8: Integrity check

```
ffmpeg -y -v error -i final.m4a -c:a pcm_s16le -f null /dev/null
```

Decodes the entire file and checks for errors. If stderr has output, something went wrong in reassembly.

### Step 9: Tag

Uses `mutagen` to write MP4/iTunes metadata atoms:

| Field | Atom | Example |
|-------|------|---------|
| Title | `©nam` | "Blue in Green" |
| Artist | `©ART` | "Miles Davis" |
| Album | `©alb` | "Kind of Blue" |
| Album artist | `aART` | "Miles Davis" |
| Genre | `©gen` | ["Jazz"] |
| Year | `©day` | "1959-08-17" |
| Track number | `trkn` | (4, 5) |
| Cover art | `covr` | JPEG bytes (1200x1200) |
| ISRC | `----:com.apple.iTunes:ISRC` | "USSM19900404" |

Cover art is downloaded from Apple's artwork CDN with `{w}` and `{h}` template variables replaced.

## External tool dependencies

| Tool | Package | Purpose |
|------|---------|---------|
| `ffmpeg` | `brew install ffmpeg` | Metadata fix pass, integrity check |
| `gpac` | `brew install gpac` | NHML sample extraction and re-muxing |
| `MP4Box` | (included with gpac) | ISO box dump, file branding |
| `mp4edit` | `brew install bento4` | Insert/replace atoms in MP4 |
| `mp4extract` | (included with bento4) | Extract atoms from MP4 |

## Security considerations

- **No credentials sent to wrapper-manager**: Our client only sends song IDs and encrypted audio samples to the wrapper-manager. The wrapper-manager uses its own Apple Music accounts for authentication. Our `APPLE_USER_TOKEN` only talks to Apple's API directly for metadata/playlist lookups — it never touches the wrapper-manager.
- **Wrapper-manager visibility**: The operator can see which songs you're decrypting (adam_ids). That's it — no account info, no personal data.
- **DRM circumvention**: This is FairPlay DRM circumvention, which implicates the DMCA (US) and equivalent laws in other jurisdictions, regardless of whether you have an active subscription.
- **Token exposure**: The `APPLE_USER_TOKEN` in `.env` grants full access to your Apple Music library. Treat it like a password — but it only goes to Apple's servers, never to third parties.

## Prior art

- [WorldObservationLog/AppleMusicDecrypt](https://github.com/WorldObservationLog/AppleMusicDecrypt) — Full-featured Python client (AGPL-3.0, ~484 stars)
- [zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) — Original Go implementation (~1700 stars), pioneered the wrapper approach
- [glomatico/gamdl](https://github.com/glomatico/gamdl) — Python, pip/brew installable (~2100 stars), AAC without wrapper, ALAC with wrapper
- [Myp3a/apple-music-api](https://github.com/Myp3a/apple-music-api) — Python wrapper, similar approach, includes DRM decryption
- [Cider](https://github.com/ciderapp/Cider) — Open-source Apple Music desktop client
- [passport-apple-music](https://www.npmjs.com/package/passport-apple-music) — Reverse-engineered MusicKit JS auth for PassportJS
