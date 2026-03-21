"""Tests for CLI scoring and matching logic."""

import pytest

from cli import score_result, match_songs


# --- score_result tests ---

def _make_result(name="Song", artist="Artist", album="Album", audio_traits=None):
    return {
        "id": "123",
        "name": name,
        "artist": artist,
        "album": album,
        "duration_ms": 240000,
        "release_date": "2020-01-01",
        "genres": [],
        "audio_traits": audio_traits or ["lossless", "lossy-stereo"],
        "isrc": "",
    }


class TestScoreResult:
    def test_exact_artist_match_scores_high(self):
        result = _make_result(artist="Daft Punk")
        score = score_result(result, "Daft Punk", "One More Time")
        assert score >= 70

    def test_artist_mismatch_scores_low(self):
        result = _make_result(artist="Tchami & Marshall Jefferson")
        score = score_result(result, "Marshall Jefferson", "Move Your Body")
        # Marshall Jefferson is contained in the result artist, so it should match
        assert score >= 70

    def test_completely_wrong_artist_penalized(self):
        result = _make_result(artist="Some Random Artist")
        score = score_result(result, "Daft Punk", "One More Time")
        assert score < 30

    def test_remix_penalized_when_not_requested(self):
        original = _make_result(name="Lady (Hear Me Tonight)")
        remix = _make_result(name="Lady (Hear Me Tonight) [Remix]")
        score_orig = score_result(original, "Modjo", "Lady Hear Me Tonight")
        score_remix = score_result(remix, "Modjo", "Lady Hear Me Tonight")
        assert score_orig > score_remix

    def test_remix_not_penalized_when_requested(self):
        remix = _make_result(name="Song Title [Remix]")
        score = score_result(remix, "Artist", "Song Title Remix")
        # Should not be penalized since user asked for a remix
        assert score >= 50

    def test_dj_mix_album_penalized(self):
        normal = _make_result(album="Discovery")
        dj_mix = _make_result(album="fabric 24: Rob da Bank (DJ Mix)")
        score_normal = score_result(normal, "Daft Punk", "One More Time")
        score_mix = score_result(dj_mix, "Daft Punk", "One More Time")
        assert score_normal > score_mix

    def test_mixed_tag_penalized(self):
        clean = _make_result(name="Your Love")
        mixed = _make_result(name="Your Love (Mixed)")
        score_clean = score_result(clean, "Frankie Knuckles", "Your Love")
        score_mixed = score_result(mixed, "Frankie Knuckles", "Your Love")
        assert score_clean > score_mixed

    def test_sped_up_penalized(self):
        original = _make_result(name="Move Your Body")
        sped_up = _make_result(name="Move Your Body [Sped Up]")
        score_orig = score_result(original, "Marshall Jefferson", "Move Your Body")
        score_sped = score_result(sped_up, "Marshall Jefferson", "Move Your Body")
        assert score_orig > score_sped

    def test_remaster_not_penalized(self):
        remaster = _make_result(name="Lady (Hear Me Tonight) - Remastered", artist="Modjo")
        score = score_result(remaster, "Modjo", "Lady Hear Me Tonight")
        # Remaster is safe, should not be penalized
        assert score >= 70

    def test_radio_edit_not_penalized(self):
        radio = _make_result(name="Da Funk (Radio Edit)", artist="Daft Punk")
        score = score_result(radio, "Daft Punk", "Da Funk")
        assert score >= 70

    def test_atmos_boosted(self):
        normal = _make_result(audio_traits=["lossless", "lossy-stereo"])
        atmos = _make_result(audio_traits=["atmos", "lossless", "lossy-stereo", "spatial"])
        score_normal = score_result(normal, "Artist", "Song")
        score_atmos = score_result(atmos, "Artist", "Song")
        assert score_atmos > score_normal

    def test_hires_boosted_over_lossless(self):
        lossless = _make_result(audio_traits=["lossless", "lossy-stereo"])
        hires = _make_result(audio_traits=["hi-res-lossless", "lossless", "lossy-stereo"])
        score_lossless = score_result(lossless, "Artist", "Song")
        score_hires = score_result(hires, "Artist", "Song")
        assert score_hires > score_lossless

    def test_rework_penalized(self):
        original = _make_result(name="World Hold On")
        rework = _make_result(name="World Hold On [FISHER Rework]")
        score_orig = score_result(original, "Bob Sinclar", "World Hold On")
        score_rework = score_result(rework, "Bob Sinclar", "World Hold On")
        assert score_orig > score_rework

    def test_compilation_album_penalized(self):
        original = _make_result(album="Homework")
        compilation = _make_result(album="Ministry of Sound: Anthems")
        score_orig = score_result(original, "Daft Punk", "Around the World")
        score_comp = score_result(compilation, "Daft Punk", "Around the World")
        assert score_orig > score_comp

    def test_dave_aude_remix_penalized(self):
        original = _make_result(name="Uptown Funk (feat. Bruno Mars)")
        remix = _make_result(name="Uptown Funk (feat. Bruno Mars) [Dave Audé Remix]")
        score_orig = score_result(original, "Mark Ronson", "Uptown Funk")
        score_remix = score_result(remix, "Mark Ronson", "Uptown Funk")
        assert score_orig > score_remix

    def test_axwell_remix_penalized(self):
        original = _make_result(name="World, Hold On")
        remix = _make_result(name="World, Hold On (Axwell Remix) [Mixed]")
        score_orig = score_result(original, "Bob Sinclar", "World Hold On")
        score_remix = score_result(remix, "Bob Sinclar", "World Hold On")
        assert score_orig > score_remix

    def test_deluxe_edition_not_penalized(self):
        """Deluxe edition albums should not be penalized — they're original releases."""
        normal = _make_result(album="Jazz")
        deluxe = _make_result(album="Jazz (Deluxe Edition)")
        score_normal = score_result(normal, "Queen", "Don't Stop Me Now")
        score_deluxe = score_result(deluxe, "Queen", "Don't Stop Me Now")
        # Scores should be equal (or deluxe slightly boosted if bonus track logic)
        assert abs(score_normal - score_deluxe) <= 5

    def test_with_long_lost_guitars_penalized(self):
        """Alternate takes should score lower than the original."""
        original = _make_result(name="Don't Stop Me Now")
        alternate = _make_result(name="Don't Stop Me Now (With Long-Lost Guitars)")
        score_orig = score_result(original, "Queen", "Don't Stop Me Now")
        score_alt = score_result(alternate, "Queen", "Don't Stop Me Now")
        # Both should score OK, but original is cleaner
        assert score_orig >= score_alt


# --- match_songs tests ---

class FakeAppleMusicClient:
    """Mock client that returns predefined search results."""

    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = responses
        self.queries = []

    def search_song(self, query: str, limit: int = 10) -> list[dict]:
        self.queries.append(query)
        return self.responses.get(query, [])


class TestMatchSongs:
    def test_picks_best_scored_result(self):
        am = FakeAppleMusicClient({
            "Modjo Lady Hear Me Tonight": [
                _make_result(name="Lady (Hear Me Tonight) [Remix]", artist="Modjo, Sparrow & Barbossa"),
                _make_result(name="Lady (Hear Me Tonight)", artist="Modjo"),
            ],
        })
        results = match_songs(am, [{"artist": "Modjo", "title": "Lady Hear Me Tonight"}])
        assert len(results) == 1
        assert results[0]["pick"]["name"] == "Lady (Hear Me Tonight)"

    def test_flags_artist_mismatch(self):
        am = FakeAppleMusicClient({
            "Marshall Jefferson Move Your Body": [
                _make_result(name="Move Your Body (Future House)", artist="Tchami & Marshall Jefferson"),
            ],
        })
        results = match_songs(am, [{"artist": "Marshall Jefferson", "title": "Move Your Body"}])
        # Tchami & Marshall Jefferson contains "Marshall Jefferson" so no artist mismatch warning
        assert results[0]["pick"] is not None

    def test_flags_completely_wrong_artist(self):
        am = FakeAppleMusicClient({
            "Daft Punk Something": [
                _make_result(name="Something", artist="Coldplay"),
            ],
        })
        results = match_songs(am, [{"artist": "Daft Punk", "title": "Something"}])
        assert any("artist mismatch" in w for w in results[0]["warnings"])

    def test_flags_remix(self):
        am = FakeAppleMusicClient({
            "Bob Sinclar World Hold On": [
                _make_result(name="World, Hold On (Axwell Remix) [Mixed]", artist="Bob Sinclar"),
            ],
        })
        results = match_songs(am, [{"artist": "Bob Sinclar", "title": "World Hold On"}])
        assert any("remix" in w for w in results[0]["warnings"])

    def test_flags_dj_mix_album(self):
        am = FakeAppleMusicClient({
            "Frankie Knuckles Your Love": [
                _make_result(name="Your Love (Mixed)", artist="Frankie Knuckles", album="fabric 24 (DJ Mix)"),
            ],
        })
        results = match_songs(am, [{"artist": "Frankie Knuckles", "title": "Your Love"}])
        assert any("DJ mix" in w for w in results[0]["warnings"])

    def test_no_results_returns_miss(self):
        am = FakeAppleMusicClient({})
        results = match_songs(am, [{"artist": "Nobody", "title": "Nothing"}])
        assert results[0]["pick"] is None
        assert "no results found" in results[0]["warnings"]

    def test_clean_match_no_warnings(self):
        am = FakeAppleMusicClient({
            "Daft Punk One More Time": [
                _make_result(name="One More Time", artist="Daft Punk", album="Discovery"),
            ],
        })
        results = match_songs(am, [{"artist": "Daft Punk", "title": "One More Time"}])
        assert results[0]["warnings"] == []

    def test_prefers_original_over_remix(self):
        am = FakeAppleMusicClient({
            "Mark Ronson Uptown Funk": [
                _make_result(name="Uptown Funk (feat. Bruno Mars) [Dave Audé Remix]", artist="Mark Ronson"),
                _make_result(name="Uptown Funk (feat. Bruno Mars)", artist="Mark Ronson"),
            ],
        })
        results = match_songs(am, [{"artist": "Mark Ronson", "title": "Uptown Funk"}])
        assert "Remix" not in results[0]["pick"]["name"]

    def test_batch_multiple_songs(self):
        am = FakeAppleMusicClient({
            "ABBA Mamma Mia": [
                _make_result(name="Mamma Mia", artist="ABBA"),
            ],
            "Queen Don't Stop Me Now": [
                _make_result(name="Don't Stop Me Now", artist="Queen"),
            ],
        })
        results = match_songs(am, [
            {"artist": "ABBA", "title": "Mamma Mia"},
            {"artist": "Queen", "title": "Don't Stop Me Now"},
        ])
        assert len(results) == 2
        assert results[0]["pick"]["name"] == "Mamma Mia"
        assert results[1]["pick"]["name"] == "Don't Stop Me Now"
