#!/usr/bin/env python3
"""Apple Music playlist CLI.

Usage:
    python cli.py create --name "Chill Jazz" --songs '[...]'
    python cli.py create --name "Chill Jazz" --songs '[...]' --upsert
    python cli.py list
    python cli.py tracks --id p.ABC123
    python cli.py update --id p.ABC123 --name "New Name" --description "New desc" --add-songs '[...]' --remove-track-ids '["i.XXX"]'
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


def resolve_songs(am: AppleMusicClient, songs_json: str | None) -> list[dict]:
    """Search Apple Music for each {artist, title} and return matched tracks."""
    if not songs_json:
        return []
    songs = json.loads(songs_json)
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
    return found


def cmd_create(args):
    am = get_client()

    # Upsert: find existing playlist by name instead of creating a duplicate
    if args.upsert:
        playlists = am.list_playlists()
        for p in playlists:
            if p["name"] == args.name:
                print(f"Found existing playlist: {args.name} ({p['id']})")
                args.id = p["id"]
                # Update description if provided
                if args.description:
                    am.update_playlist(p["id"], description=args.description)
                # Add songs if provided
                found = resolve_songs(am, args.songs)
                if found:
                    track_ids = [t["id"] for t in found]
                    am.add_tracks(p["id"], track_ids)
                    print(f"Added {len(found)} tracks.")
                return

    found = resolve_songs(am, args.songs)
    if not found:
        print("\nNo tracks found on Apple Music.")
        sys.exit(1)

    print(f"\nMatched {len(found)}/{len(json.loads(args.songs))} tracks")

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

    did_something = False

    # Update metadata
    name = args.name if args.name else None
    desc = args.description if args.description else None
    if name is not None or desc is not None:
        am.update_playlist(args.id, name=name, description=desc)
        print("Metadata updated.")
        did_something = True

    # Remove tracks
    if args.remove_track_ids:
        track_ids = json.loads(args.remove_track_ids)
        am.remove_tracks(args.id, track_ids)
        print(f"Removed {len(track_ids)} tracks.")
        did_something = True

    # Add songs by {artist, title} search
    if args.add_songs:
        found = resolve_songs(am, args.add_songs)
        if found:
            track_ids = [t["id"] for t in found]
            am.add_tracks(args.id, track_ids)
            print(f"Added {len(found)} tracks.")
            did_something = True

    # Add tracks by catalog ID directly
    if args.add_track_ids:
        track_ids = json.loads(args.add_track_ids)
        am.add_tracks(args.id, track_ids)
        print(f"Added {len(track_ids)} tracks by ID.")
        did_something = True

    if not did_something:
        print("Nothing to do. Use --name, --description, --add-songs, --add-track-ids, or --remove-track-ids.")
        sys.exit(1)


def cmd_rebuild(args):
    am = get_client()
    track_ids = json.loads(args.track_ids)
    new_id = am.replace_all_tracks(args.id, track_ids)
    print(f"Rebuilt playlist with {len(track_ids)} tracks. New ID: {new_id}")


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
    p_create.add_argument("--upsert", action="store_true", help="Add to existing playlist with same name instead of creating duplicate")

    # list
    sub.add_parser("list", help="List all playlists")

    # tracks
    p_tracks = sub.add_parser("tracks", help="List tracks in a playlist")
    p_tracks.add_argument("--id", required=True, help="Playlist ID")

    # update — does everything: metadata, add, remove
    p_update = sub.add_parser("update", help="Update playlist: metadata, add/remove tracks")
    p_update.add_argument("--id", required=True, help="Playlist ID")
    p_update.add_argument("--name", help="New playlist name")
    p_update.add_argument("--description", help="New playlist description")
    p_update.add_argument("--add-songs", help="JSON array of {artist, title} to search and add")
    p_update.add_argument("--add-track-ids", help="JSON array of catalog song IDs to add directly")
    p_update.add_argument("--remove-track-ids", help="JSON array of library-song IDs to remove")

    # rebuild — replace all tracks in a specific order
    p_rebuild = sub.add_parser("rebuild", help="Replace all tracks in a playlist with a new ordered list")
    p_rebuild.add_argument("--id", required=True, help="Playlist ID")
    p_rebuild.add_argument("--track-ids", required=True, help="JSON array of catalog song IDs in desired order")

    # search
    p_search = sub.add_parser("search", help="Search Apple Music catalog")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=3)

    args = parser.parse_args()

    try:
        {"create": cmd_create, "list": cmd_list, "tracks": cmd_tracks,
         "update": cmd_update, "rebuild": cmd_rebuild, "search": cmd_search}[args.command](args)
    except TokenExpiredError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
