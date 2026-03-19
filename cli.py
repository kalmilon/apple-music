#!/usr/bin/env python3
"""Push songs to Apple Music as a playlist.

Usage:
    python cli.py --name "My Playlist" --songs '[{"artist": "Miles Davis", "title": "Blue in Green"}]'
    echo '<json>' | python cli.py --name "My Playlist"
"""

import argparse
import json
import sys
import os

from dotenv import load_dotenv

load_dotenv()

from apple_music import AppleMusicClient, TokenExpiredError, fetch_dev_token


def get_dev_token() -> str:
    """Get dev token from env, or auto-scrape it."""
    token = os.environ.get("APPLE_DEV_TOKEN", "").strip()
    if token:
        return token
    print("No APPLE_DEV_TOKEN set, scraping from Apple Music web player...")
    token = fetch_dev_token()
    print("  Got dev token.")
    return token


def main():
    parser = argparse.ArgumentParser(description="Create an Apple Music playlist from a list of songs")
    parser.add_argument("--name", required=True, help="Playlist name")
    parser.add_argument("--description", default="", help="Playlist description")
    parser.add_argument("--songs", help='JSON array of {artist, title} objects')
    args = parser.parse_args()

    # Accept songs from --songs arg or stdin
    if args.songs:
        songs = json.loads(args.songs)
    else:
        songs = json.loads(sys.stdin.read())

    if not songs:
        print("No songs provided.")
        sys.exit(1)

    user_token = os.environ.get("APPLE_USER_TOKEN", "").strip()
    if not user_token:
        print("APPLE_USER_TOKEN not set in .env")
        sys.exit(1)

    try:
        am = AppleMusicClient(
            dev_token=get_dev_token(),
            user_token=user_token,
            storefront=os.environ.get("APPLE_STOREFRONT", "za"),
        )

        # Search for each song
        found = []
        for song in songs:
            query = f"{song['artist']} {song['title']}"
            result = am.search_song(query)
            if result:
                print(f"  found: {result['artist']} - {result['name']}")
                found.append(result)
            else:
                print(f"  miss:  {song['artist']} - {song['title']}")

        if not found:
            print("\nNo tracks found on Apple Music.")
            sys.exit(1)

        print(f"\nMatched {len(found)}/{len(songs)} tracks")

        # Create playlist and add tracks
        playlist_id = am.create_playlist(args.name, args.description)
        print(f"Created playlist: {args.name} ({playlist_id})")

        track_ids = [t["id"] for t in found]
        if am.add_tracks(playlist_id, track_ids):
            print(f"Added {len(found)} tracks. Check your Apple Music library.")
        else:
            print("Failed to add tracks.")
            sys.exit(1)

    except TokenExpiredError as e:
        print(f"\n{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
