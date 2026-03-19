"""Minimal Apple Music API client — search, create playlist, add tracks."""

import requests

BASE_URL = "https://amp-api.music.apple.com"


class AppleMusicClient:
    def __init__(self, dev_token: str, user_token: str, storefront: str = "za"):
        self.storefront = storefront
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {dev_token}",
            "Music-User-Token": user_token,
            "Origin": "https://music.apple.com",
        })

    def search_song(self, query: str) -> dict | None:
        """Search catalog for a song. Returns first match or None."""
        resp = self.session.get(
            f"{BASE_URL}/v1/catalog/{self.storefront}/search",
            params={"term": query, "types": "songs", "limit": 1},
        )
        resp.raise_for_status()
        data = resp.json()
        songs = data.get("results", {}).get("songs", {}).get("data", [])
        if not songs:
            return None
        song = songs[0]
        return {
            "id": song["id"],
            "name": song["attributes"]["name"],
            "artist": song["attributes"]["artistName"],
            "album": song["attributes"].get("albumName", ""),
        }

    def create_playlist(self, name: str, description: str = "") -> str:
        """Create a new library playlist. Returns playlist ID."""
        resp = self.session.post(
            f"{BASE_URL}/v1/me/library/playlists",
            json={
                "attributes": {"name": name, "description": description},
                "relationships": {"tracks": {"data": []}},
            },
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["id"]

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> bool:
        """Add catalog tracks to a library playlist."""
        resp = self.session.post(
            f"{BASE_URL}/v1/me/library/playlists/{playlist_id}/tracks",
            json={"data": [{"id": tid, "type": "songs"} for tid in track_ids]},
        )
        return resp.status_code in (200, 201, 204)
