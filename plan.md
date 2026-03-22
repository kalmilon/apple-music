# Plan: Native Wrapper Client — Kill the Bloat

## Context

We currently have a 280MB Docker image running a Go wrapper-manager that speaks gRPC, just to proxy TCP calls to a 100KB C binary that does the actual decryption. The wrapper-manager is unnecessary middleware. The wrapper binary itself exposes a dead-simple TCP protocol on three ports. We can talk to it directly.

**Current stack (bloated):**
```
cli.py → gRPC/protobuf → wrapper-manager (Go, 280MB) → TCP → wrapper (C, 100KB)
```

**Target stack (cracked):**
```
cli.py → raw TCP socket → wrapper (C, 100KB in minimal Docker, ~50MB)
```

No Go. No gRPC. No protobuf. Just raw TCP.

## Key Finding: The Decrypt Protocol

Port 10020 speaks a trivial binary protocol:

```
SETUP (once per song):
  → uint8   adam_id_length
  → bytes   adam_id (ascii)
  → uint8   uri_length
  → bytes   skd_uri (ascii)

SAMPLE LOOP (repeated):
  → uint32  sample_size (big-endian, 0 = done)
  → bytes   encrypted_sample[sample_size]
  ← bytes   decrypted_sample[sample_size]
```

That's it. No headers, no framing, no negotiation. We can implement this in ~30 lines of Python.

Port 20020 (M3U8) and 30020 (login) have similarly simple protocols.

## Architecture

```
┌──────────────┐                    ┌─────────────────────────┐
│   cli.py     │   TCP :10020      │  Docker (minimal)       │
│              │──────────────────►│  wrapper (C binary)     │
│  downloader  │   TCP :20020      │  + rootfs (~50MB)       │
│  .py         │──────────────────►│  + libandroidappmusic   │
│              │   TCP :30020      │                         │
│              │──────────────────►│  Alpine Linux base      │
└──────────────┘                    └─────────────────────────┘
```

## Implementation Plan

### Step 1: Test the TCP decrypt protocol
**File:** `test_cli.py`

Write tests for the binary protocol serialization/deserialization:
- `test_pack_decrypt_setup` — verify adam_id + uri packing
- `test_pack_sample_request` — verify uint32 big-endian + sample bytes
- `test_parse_decrypt_response` — verify reading back same-size decrypted bytes
- `test_zero_terminates` — verify sending size=0 ends the session

### Step 2: Build the TCP wrapper client
**File:** `downloader.py` — new class `WrapperClient`

Replace `WrapperManagerClient` (gRPC) with `WrapperClient` (raw TCP):
- `decrypt_samples(adam_id, uri, samples)` — opens TCP to :10020, sends setup, loops samples
- `get_m3u8(adam_id)` — TCP to :20020, sends adam_id, reads back M3U8 URL
- `login(username, password)` — TCP to :30020 for initial auth

### Step 3: Minimal Docker image
**File:** `Dockerfile` (in project root)

```dockerfile
FROM alpine:latest
RUN apk add --no-cache ca-certificates
COPY wrapper /app/wrapper
COPY rootfs /app/rootfs
WORKDIR /app
ENTRYPOINT ["./wrapper"]
```

Download the wrapper release binary directly from GitHub (not build from source). Target: <100MB image.

### Step 4: Docker Compose for local dev
**File:** `docker-compose.yml` (in project root)

```yaml
services:
  wrapper:
    build: .
    privileged: true
    ports:
      - "10020:10020"
      - "20020:20020"
      - "30020:30020"
```

### Step 5: Login command
**File:** `cli.py` — new `cmd_login` subcommand

```bash
uv run python cli.py login --username user@example.com --password xxx
```

Handles 2FA via stdin prompt.

### Step 6: Wire up download command
**File:** `cli.py`, `downloader.py`

Update `cmd_download` to use `WrapperClient` instead of `WrapperManagerClient`. Config via `.env`:
```
WRAPPER_HOST=localhost
WRAPPER_DECRYPT_PORT=10020
WRAPPER_M3U8_PORT=20020
```

No fallback. gRPC path is deleted.

### Step 7: Integration test
End-to-end: login → download one song → verify .m4a plays → integrity check.

## Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `downloader.py` | Modify | Replace `WrapperManagerClient` with `WrapperClient` (TCP) |
| `cli.py` | Modify | Add `login` command, update `download` to use TCP client |
| `test_cli.py` | Modify | Add TCP protocol tests |
| `Dockerfile` | Create | Minimal wrapper image |
| `docker-compose.yml` | Create | Local wrapper service |
| `.gitignore` | Modify | Add wrapper binary/rootfs |

## What We Delete

- `proto/` directory (manager.proto, generated stubs)
- `grpcio`, `grpcio-tools`, `protobuf` dependencies (~31MB gone)
- `wrapper-manager/` clone
- `WrapperManagerClient` class from downloader.py
- All gRPC imports and references

## Dependency Reduction

**Before:** grpcio (25MB), grpcio-tools (5MB), protobuf (1MB) = ~31MB of Python deps
**After:** zero new deps. Just `socket` (stdlib).

## Test Plan

1. Unit tests for TCP protocol pack/unpack (no Docker needed)
2. Start Docker wrapper locally
3. Run login command
4. Download single song, verify .m4a integrity
5. Download playlist, verify all tracks
6. Run `uv run pytest test_cli.py` for all tests

## Why Docker Is Unavoidable

The wrapper binary loads `libandroidappmusic.so` (Apple's Android FairPlay library) using:
- `chroot()` — Linux-only syscall
- `unshare(CLONE_NEWPID)` — Linux-only namespace
- Android's `linker64` — Linux ELF dynamic linker
- Bionic libc — Android's C library, not compatible with macOS

These are Linux kernel primitives. No amount of RE gets around this — the .so files are closed-source Android binaries. We can't recompile them for macOS. Docker is the thinnest possible Linux layer (~50MB Alpine vs ~3GB full VM).

## Risks

- **Wrapper binary architecture**: ARM64 Linux build exists but may be fragile on Apple Silicon Docker. Fallback: x86_64 build via Rosetta emulation in Docker.
- **Login protocol**: Port 30020 protocol needs investigation. May need to reverse-engineer from wrapper.c source.
- **M3U8 protocol**: Port 20020 protocol also needs investigation.
