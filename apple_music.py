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

    def search_song(self, query: str) -> dict | None:
        """Search catalog for a song. Returns first match or None."""
        resp = self.session.get(
            f"{BASE_URL}/v1/catalog/{self.storefront}/search",
            params={"term": query, "types": "songs", "limit": 1},
        )
        self._check_response(resp)
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
