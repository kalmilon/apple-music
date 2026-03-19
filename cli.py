#!/usr/bin/env python3
"""Apple Music playlist CLI.

Usage:
    python cli.py create --name "Chill Jazz" --songs '[...]'
    python cli.py list
    python cli.py tracks --id p.ABC123
    python cli.py update --id p.ABC123 --name "New Name" --description "New desc"
    python cli.py add --id p.ABC123 --songs '[...]'
    python cli.py remove --id p.ABC123 --track-ids '["i.XXX", "i.YYY"]'
    python cli.py search --query "Miles Davis Blue in Green"
"""

import argparse
import json
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


def read_songs(args) -> list[dict]:
    """Read songs from --songs arg or stdin."""
    if args.songs:
        return json.loads(args.songs)
    if not sys.stdin.isatty():
        return json.loads(sys.stdin.read())
    print("No songs provided. Use --songs or pipe JSON to stdin.")
    sys.exit(1)


def cmd_create(args):
    am = get_client()
    songs = read_songs(args)

    found = []
    for song in songs:
        query = f"{song['artist']} {song['title']}"
        results = am.search_song(query)
        if results:
            pick = results[0]
            print(f"  found: {pick['artist']} - {pick['name']}")
            found.append(pick)
        else:
            print(f"  miss:  {song['artist']} - {song['title']}")

    if not found:
        print("\nNo tracks found on Apple Music.")
        sys.exit(1)

    print(f"\nMatched {len(found)}/{len(songs)} tracks")

    playlist_id = am.create_playlist(args.name, args.description or "")
    print(f"Created playlist: {args.name} ({playlist_id})")

    track_ids = [t["id"] for t in found]
    am.add_tracks(playlist_id, track_ids)
    print(f"Added {len(found)} tracks.")


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


def cmd_update(args):
    am = get_client()
    name = args.name if args.name else None
    desc = args.description if args.description else None
    if name is None and desc is None:
        print("Nothing to update. Use --name and/or --description.")
        sys.exit(1)
    am.update_playlist(args.id, name=name, description=desc)
    print("Playlist updated.")


def cmd_add(args):
    am = get_client()
    songs = read_songs(args)

    found = []
    for song in songs:
        query = f"{song['artist']} {song['title']}"
        results = am.search_song(query)
        if results:
            pick = results[0]
            print(f"  found: {pick['artist']} - {pick['name']}")
            found.append(pick)
        else:
            print(f"  miss:  {song['artist']} - {song['title']}")

    if not found:
        print("\nNo tracks found on Apple Music.")
        sys.exit(1)

    track_ids = [t["id"] for t in found]
    am.add_tracks(args.id, track_ids)
    print(f"Added {len(found)} tracks.")


def cmd_remove(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)
    am.remove_tracks(args.id, track_ids)
    print(f"Removed {len(track_ids)} tracks.")


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


def main():
    parser = argparse.ArgumentParser(description="Apple Music playlist CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Create a new playlist")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--description", default="")
    p_create.add_argument("--songs", help="JSON array of {artist, title}")

    # list
    sub.add_parser("list", help="List all playlists")

    # tracks
    p_tracks = sub.add_parser("tracks", help="List tracks in a playlist")
    p_tracks.add_argument("--id", required=True, help="Playlist ID")

    # update
    p_update = sub.add_parser("update", help="Update playlist metadata")
    p_update.add_argument("--id", required=True, help="Playlist ID")
    p_update.add_argument("--name")
    p_update.add_argument("--description")

    # add
    p_add = sub.add_parser("add", help="Add songs to an existing playlist")
    p_add.add_argument("--id", required=True, help="Playlist ID")
    p_add.add_argument("--songs", help="JSON array of {artist, title}")

    # remove
    p_remove = sub.add_parser("remove", help="Remove tracks from a playlist")
    p_remove.add_argument("--id", required=True, help="Playlist ID")
    p_remove.add_argument("--track-ids", required=True, help="JSON array of library-song IDs")

    # search
    p_search = sub.add_parser("search", help="Search Apple Music catalog")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=3)

    args = parser.parse_args()

    try:
        {"create": cmd_create, "list": cmd_list, "tracks": cmd_tracks,
         "update": cmd_update, "add": cmd_add, "remove": cmd_remove,
         "search": cmd_search}[args.command](args)
    except TokenExpiredError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
