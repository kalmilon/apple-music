"""Minimal Apple Music API client — search, create playlist, add tracks."""

import re
import sys

import requests

BASE_URL = "https://amp-api.music.apple.com"


class TokenExpiredError(Exception):
    pass


def fetch_dev_token() -> str:
    """Scrape the developer token from Apple Music's web player JS bundle."""
    resp = requests.get("https://music.apple.com")
    resp.raise_for_status()
    # Find JS bundle URLs and check each for a JWT
    js_urls = re.findall(r'(?:src|href)=["\'](/assets/[^"\']*\.js)["\']', resp.text)
    for js_path in js_urls:
        js_resp = requests.get(f"https://music.apple.com{js_path}")
        js_resp.raise_for_status()
        token_match = re.search(r'eyJh[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', js_resp.text)
        if token_match:
            return token_match.group(0)
    raise RuntimeError("Could not find developer token in any JS bundle")


class AppleMusicClient:
    def __init__(self, dev_token: str, user_token: str, storefront: str = "za"):
        self.storefront = storefront
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {dev_token}",
            "Music-User-Token": user_token,
            "Origin": "https://music.apple.com",
        })

    def _check_response(self, resp: requests.Response) -> None:
        if resp.status_code == 401 or resp.status_code == 403:
            raise TokenExpiredError(
                "User token expired. Refresh it:\n"
                "  1. Open https://music.apple.com in your browser\n"
                "  2. Open DevTools (Cmd+Option+I) → Network tab\n"
                "  3. Click any song/playlist\n"
                "  4. Copy the 'media-user-token' header value\n"
                "  5. Update APPLE_USER_TOKEN in .env"
            )
        resp.raise_for_status()

    def search_song(self, query: str, limit: int = 3) -> list[dict]:
        """Search catalog for a song. Returns top matches."""
        resp = self.session.get(
            f"{BASE_URL}/v1/catalog/{self.storefront}/search",
            params={"term": query, "types": "songs", "limit": limit},
        )
        self._check_response(resp)
        data = resp.json()
        songs = data.get("results", {}).get("songs", {}).get("data", [])
        return [
            {
                "id": song["id"],
                "name": song["attributes"]["name"],
                "artist": song["attributes"]["artistName"],
                "album": song["attributes"].get("albumName", ""),
                "duration_ms": song["attributes"].get("durationInMillis"),
                "release_date": song["attributes"].get("releaseDate", ""),
                "genres": song["attributes"].get("genreNames", []),
                "audio_traits": song["attributes"].get("audioTraits", []),
                "isrc": song["attributes"].get("isrc", ""),
            }
            for song in songs
        ]

    def create_playlist(self, name: str, description: str = "") -> str:
        """Create a new library playlist. Returns playlist ID."""
        resp = self.session.post(
            f"{BASE_URL}/v1/me/library/playlists",
            json={
                "attributes": {"name": name, "description": description},
                "relationships": {"tracks": {"data": []}},
            },
        )
        self._check_response(resp)
        return resp.json()["data"][0]["id"]

    def add_tracks(self, playlist_id: str, track_ids: list[str]) -> bool:
        """Add catalog tracks to a library playlist."""
        resp = self.session.post(
            f"{BASE_URL}/v1/me/library/playlists/{playlist_id}/tracks",
            json={"data": [{"id": tid, "type": "songs"} for tid in track_ids]},
        )
        self._check_response(resp)
        return resp.status_code in (200, 201, 204)

    def list_playlists(self) -> list[dict]:
        """List all library playlists."""
        playlists = []
        url = f"{BASE_URL}/v1/me/library/playlists"
        while url:
            resp = self.session.get(url)
            self._check_response(resp)
            data = resp.json()
            for p in data["data"]:
                attrs = p.get("attributes", {})
                if "name" not in attrs:
                    continue
                playlists.append({
                    "id": p["id"],
                    "name": attrs["name"],
                    "description": attrs.get("description", {}).get("standard", ""),
                })
            url = data.get("next")
            if url:
                url = f"{BASE_URL}{url}"
        return playlists

    def get_playlist_tracks(self, playlist_id: str) -> list[dict]:
        """Get all tracks in a library playlist."""
        tracks = []
        url = f"{BASE_URL}/v1/me/library/playlists/{playlist_id}/tracks"
        while url:
            resp = self.session.get(url)
            self._check_response(resp)
            data = resp.json()
            for t in data.get("data", []):
                tracks.append({
                    "id": t["id"],
                    "type": t["type"],
                    "name": t["attributes"]["name"],
                    "artist": t["attributes"]["artistName"],
                    "album": t["attributes"].get("albumName", ""),
                })
            url = data.get("next")
            if url:
                url = f"{BASE_URL}{url}"
        return tracks

    def remove_tracks(self, playlist_id: str, track_ids: list[str]) -> bool:
        """Remove tracks from a library playlist by library-song ID."""
        for tid in track_ids:
            resp = self.session.delete(
                f"{BASE_URL}/v1/me/library/playlists/{playlist_id}/tracks",
                params={"ids[library-songs]": tid, "mode": "all"},
            )
            self._check_response(resp)
        return True

    def replace_all_tracks(self, playlist_id: str, track_ids: list[str]) -> bool:
        """Remove all tracks and re-add in the given order. Used for resequencing."""
        existing = self.get_playlist_tracks(playlist_id)
        if existing:
            self.remove_tracks(playlist_id, [t["id"] for t in existing])
        if track_ids:
            self.add_tracks(playlist_id, track_ids)
        return True

    def update_playlist(self, playlist_id: str, name: str | None = None, description: str | None = None) -> bool:
        """Update playlist name and/or description. Only works on playlists you created (canEdit: true)."""
        if name is None and description is None:
            return True
        # PUT requires both fields — fetch current values for any we're not changing
        resp = self.session.get(f"{BASE_URL}/v1/me/library/playlists/{playlist_id}")
        self._check_response(resp)
        current = resp.json()["data"][0]["attributes"]
        attrs = {
            "name": name if name is not None else current.get("name", ""),
            "description": description if description is not None else current.get("description", {}).get("standard", ""),
        }
        resp = self.session.put(
            f"{BASE_URL}/v1/me/library/playlists/{playlist_id}",
            json={"attributes": attrs},
        )
        self._check_response(resp)
        return resp.status_code == 204
