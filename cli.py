#!/usr/bin/env python3
"""Apple Music playlist CLI.

Usage:
    python cli.py match --songs '[{"artist": "Daft Punk", "title": "One More Time"}]'
    python cli.py search --query "Miles Davis Blue in Green"
    python cli.py create --name "Chill Jazz" --track-ids '["123", "456"]'
    python cli.py create --name "Chill Jazz" --track-ids '["123"]' --upsert
    python cli.py list
    python cli.py tracks --id p.ABC123
    python cli.py add --id p.ABC123 --track-ids '["123", "456"]'
    python cli.py remove --id p.ABC123 --track-ids '["i.XXX", "i.YYY"]'
    python cli.py rename --id p.ABC123 --name "New Name" --description "New desc"
    python cli.py reorder --id p.ABC123 --track-ids '["123", "456", "789"]'
"""

import argparse
import json
import re
import sys
import os

from dotenv import load_dotenv

load_dotenv()

from apple_music import AppleMusicClient, TokenExpiredError, fetch_dev_token


def get_client() -> AppleMusicClient:
    user_token = os.environ.get("APPLE_USER_TOKEN", "").strip()
    if not user_token:
        print("APPLE_USER_TOKEN not set in .env")
        sys.exit(1)
    dev_token = os.environ.get("APPLE_DEV_TOKEN", "").strip()
    if not dev_token:
        dev_token = fetch_dev_token()
    return AppleMusicClient(
        dev_token=dev_token,
        user_token=user_token,
        storefront=os.environ.get("APPLE_STOREFRONT", "za"),
    )


# --- Scoring logic ---

REMIX_PATTERNS = re.compile(
    r"\b(remix|remixed|rmx|mix(?:ed)?|rework|bootleg|sped up|slowed|edit(?:ed)?)\b"
    r"|"
    r"\[.*(?:remix|mix|rework|version).*\]",
    re.IGNORECASE,
)

DJ_MIX_PATTERNS = re.compile(
    r"\b(dj mix|mixed|ministry of sound|fabric \d|ibiza|essential mix)\b",
    re.IGNORECASE,
)

# Words that are part of the original title, not remix indicators
SAFE_TITLE_WORDS = re.compile(
    r"\b(radio edit|original|remaster(?:ed)?|deluxe|bonus track)\b",
    re.IGNORECASE,
)


def score_result(result: dict, requested_artist: str, requested_title: str) -> int:
    """Score a search result. Higher = better match. Range roughly 0-100."""
    score = 50  # baseline

    name = result.get("name", "")
    artist = result.get("artist", "")
    album = result.get("album", "")

    # --- Artist match (biggest signal) ---
    req_lower = requested_artist.lower()
    art_lower = artist.lower()
    # Split both into word sets for comparison
    req_words = set(req_lower.split())
    art_words = set(art_lower.split())
    # Filter out short words (a, &, the, ft, feat, vs) for matching
    noise = {"a", "an", "the", "&", "ft", "ft.", "feat", "feat.", "vs", "vs.", "and"}
    req_significant = req_words - noise
    art_significant = art_words - noise
    if req_significant and req_significant <= art_significant:
        # All significant requested words are in the result artist
        score += 25
    elif req_significant and len(req_significant & art_significant) / len(req_significant) >= 0.5:
        # At least half the words match
        score += 10
    else:
        score -= 30  # wrong artist entirely

    # --- Remix/mix penalty ---
    # Check if the name has remix indicators that aren't in the requested title
    name_without_safe = SAFE_TITLE_WORDS.sub("", name)
    if REMIX_PATTERNS.search(name_without_safe):
        req_title_lower = requested_title.lower()
        # Only penalize if the user didn't ask for a remix
        if not REMIX_PATTERNS.search(req_title_lower):
            score -= 25

    # --- DJ mix / compilation album penalty ---
    if DJ_MIX_PATTERNS.search(album):
        score -= 15

    # --- Audio quality boost ---
    traits = result.get("audio_traits", [])
    if "atmos" in traits or "spatial" in traits:
        score += 5
    if "hi-res-lossless" in traits:
        score += 3
    elif "lossless" in traits:
        score += 1

    return score


def match_songs(am: AppleMusicClient, songs: list[dict]) -> list[dict]:
    """Batch search and score. Returns list of {request, pick, score, warnings}."""
    results = []
    for song in songs:
        query = f"{song['artist']} {song['title']}"
        candidates = am.search_song(query, limit=10)
        if not candidates:
            results.append({
                "request": song,
                "pick": None,
                "score": 0,
                "warnings": ["no results found"],
            })
            continue

        scored = []
        for c in candidates:
            s = score_result(c, song["artist"], song["title"])
            scored.append((s, c))
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best = scored[0]
        warnings = []

        # Flag potential issues
        noise = {"a", "an", "the", "&", "ft", "ft.", "feat", "feat.", "vs", "vs.", "and"}
        req_words = set(song["artist"].lower().split()) - noise
        pick_words = set(best["artist"].lower().split()) - noise
        if req_words and not (req_words <= pick_words):
            warnings.append(f"artist mismatch: requested '{song['artist']}', got '{best['artist']}'")

        name_without_safe = SAFE_TITLE_WORDS.sub("", best.get("name", ""))
        if REMIX_PATTERNS.search(name_without_safe) and not REMIX_PATTERNS.search(song["title"]):
            warnings.append("remix/mix version")

        if DJ_MIX_PATTERNS.search(best.get("album", "")):
            warnings.append("from DJ mix/compilation")

        results.append({
            "request": song,
            "pick": best,
            "score": best_score,
            "warnings": warnings,
        })
    return results


# --- Commands ---

def cmd_match(args):
    am = get_client()
    songs = json.loads(args.songs)
    results = match_songs(am, songs)

    warn_count = 0
    miss_count = 0
    for r in results:
        req = r["request"]
        pick = r["pick"]
        if pick is None:
            print(f"  ✗ {req['artist']} - {req['title']}  (no results)")
            miss_count += 1
        elif r["warnings"]:
            flags = ", ".join(r["warnings"])
            print(f"  ⚠ {pick['id']}  {pick['artist']} - {pick['name']}  ({flags})")
            warn_count += 1
        else:
            print(f"  ✓ {pick['id']}  {pick['artist']} - {pick['name']}")

    total = len(results)
    ok = total - warn_count - miss_count
    print(f"\n{ok} matched, {warn_count} warnings, {miss_count} missed out of {total}")


def cmd_search(args):
    am = get_client()
    results = am.search_song(args.query, limit=args.limit)
    if not results:
        print("No results.")
        return
    for r in results:
        mins = r["duration_ms"] // 60000
        secs = (r["duration_ms"] % 60000) // 1000
        traits = ", ".join(r["audio_traits"])
        print(f"  {r['id']}  {r['artist']} - {r['name']} ({r['album']}, {r['release_date']}, {mins}:{secs:02d}, {traits})")


def cmd_create(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)

    # Upsert: find existing playlist by name instead of creating a duplicate
    if args.upsert:
        playlists = am.list_playlists()
        for p in playlists:
            if p["name"] == args.name:
                print(f"Found existing playlist: {args.name} ({p['id']})")
                if args.description:
                    am.update_playlist(p["id"], description=args.description)
                if track_ids:
                    am.add_tracks(p["id"], track_ids)
                    print(f"Added {len(track_ids)} tracks.")
                return

    playlist_id = am.create_playlist(args.name, args.description or "")
    print(f"Created playlist: {args.name} ({playlist_id})")

    if track_ids:
        am.add_tracks(playlist_id, track_ids)
        print(f"Added {len(track_ids)} tracks.")


def cmd_list(args):
    am = get_client()
    playlists = am.list_playlists()
    for p in playlists:
        print(f"  {p['id']}  {p['name']}")


def cmd_tracks(args):
    am = get_client()
    tracks = am.get_playlist_tracks(args.id)
    for t in tracks:
        print(f"  {t['id']}  {t['artist']} - {t['name']} ({t['album']})")


def cmd_add(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)
    am.add_tracks(args.id, track_ids)
    print(f"Added {len(track_ids)} tracks.")


def cmd_remove(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)
    am.remove_tracks(args.id, track_ids)
    print(f"Removed {len(track_ids)} tracks.")


def cmd_rename(args):
    am = get_client()
    name = args.name if args.name else None
    desc = args.description if args.description else None
    if name is None and desc is None:
        print("Nothing to do. Use --name and/or --description.")
        sys.exit(1)
    am.update_playlist(args.id, name=name, description=desc)
    print("Updated.")


def cmd_reorder(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)
    new_id = am.replace_all_tracks(args.id, track_ids)
    print(f"Reordered playlist. New ID: {new_id}")


def main():
    parser = argparse.ArgumentParser(description="Apple Music playlist CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # match
    p_match = sub.add_parser("match", help="Find songs on Apple Music (batch search with scoring)")
    p_match.add_argument("--songs", required=True, help="JSON array of {artist, title}")

    # search
    p_search = sub.add_parser("search", help="Look up a specific song")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)

    # create
    p_create = sub.add_parser("create", help="Make a playlist")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--track-ids", required=True, help="JSON array of catalog song IDs")
    p_create.add_argument("--upsert", action="store_true", help="Add to existing playlist with same name")

    # list
    sub.add_parser("list", help="List all playlists")

    # tracks
    p_tracks = sub.add_parser("tracks", help="Show tracks in a playlist")
    p_tracks.add_argument("--id", required=True, help="Playlist ID")

    # add
    p_add = sub.add_parser("add", help="Add songs to a playlist")
    p_add.add_argument("--id", required=True, help="Playlist ID")
    p_add.add_argument("--track-ids", required=True, help="JSON array of catalog song IDs")

    # remove
    p_remove = sub.add_parser("remove", help="Remove songs from a playlist")
    p_remove.add_argument("--id", required=True, help="Playlist ID")
    p_remove.add_argument("--track-ids", required=True, help="JSON array of library-song IDs")

    # rename
    p_rename = sub.add_parser("rename", help="Rename or redescribe a playlist")
    p_rename.add_argument("--id", required=True, help="Playlist ID")
    p_rename.add_argument("--name", help="New playlist name")
    p_rename.add_argument("--description", help="New playlist description")

    # reorder
    p_reorder = sub.add_parser("reorder", help="Reorder a playlist")
    p_reorder.add_argument("--id", required=True, help="Playlist ID")
    p_reorder.add_argument("--track-ids", required=True, help="JSON array of catalog song IDs in desired order")

    args = parser.parse_args()

    try:
        {
            "match": cmd_match, "search": cmd_search, "create": cmd_create,
            "list": cmd_list, "tracks": cmd_tracks, "add": cmd_add,
            "remove": cmd_remove, "rename": cmd_rename, "reorder": cmd_reorder,
        }[args.command](args)
    except TokenExpiredError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
