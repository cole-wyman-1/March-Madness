"""Tests for Barttorvik ratings integration."""

import pytest

from src.ncaa.ratings import RatingsProvider, TeamRating, _normalize_name
from src.ncaa.matchups import (
    build_matchup_fn,
    efficiency_win_prob,
    seed_win_prob,
)
from src.data.models import Team, TournamentState


# ---- Fixtures ----

@pytest.fixture
def ratings():
    """RatingsProvider loaded with a few sample teams."""
    rp = RatingsProvider()
    rp.load_from_dict({
        "Duke": {"adj_o": 120.0, "adj_d": 90.0, "adj_tempo": 70.0},
        "North Carolina": {"adj_o": 115.0, "adj_d": 92.0, "adj_tempo": 69.0},
        "Connecticut": {"adj_o": 125.0, "adj_d": 88.0, "adj_tempo": 68.0},
        "Weak Team": {"adj_o": 95.0, "adj_d": 110.0, "adj_tempo": 66.0},
    })
    return rp


@pytest.fixture
def state():
    """TournamentState with matching teams."""
    return TournamentState(
        year=2026,
        teams=[
            Team(name="Duke", seed=1, region="East"),
            Team(name="UNC", seed=2, region="East"),
            Team(name="UConn", seed=1, region="West"),
            Team(name="Weak Team", seed=16, region="West"),
            Team(name="Unknown Team", seed=8, region="South"),
            Team(name="Other Unknown", seed=9, region="South"),
        ],
    )


# ---- RatingsProvider tests ----

class TestRatingsProvider:
    def test_is_loaded(self, ratings):
        assert ratings.is_loaded

    def test_empty_provider(self):
        rp = RatingsProvider()
        assert not rp.is_loaded
        assert rp.get("Duke") is None

    def test_exact_match(self, ratings):
        r = ratings.get("Duke")
        assert r is not None
        assert r.adj_o == 120.0
        assert r.adj_d == 90.0

    def test_alias_match(self, ratings):
        # "UConn" -> "Connecticut" via NAME_ALIASES
        r = ratings.get("UConn")
        assert r is not None
        assert r.name == "Connecticut"
        assert r.adj_o == 125.0

    def test_alias_match_uppercase(self, ratings):
        r = ratings.get("UCONN")
        assert r is not None
        assert r.name == "Connecticut"

    def test_alias_unc(self, ratings):
        r = ratings.get("UNC")
        assert r is not None
        assert r.name == "North Carolina"

    def test_normalized_match(self, ratings):
        # "north carolina" should match "North Carolina" via normalization
        r = ratings.get("north carolina")
        assert r is not None

    def test_no_match(self, ratings):
        assert ratings.get("Nonexistent University") is None

    def test_team_rating_properties(self, ratings):
        r = ratings.get("Duke")
        assert r.adj_em == 30.0  # 120 - 90
        assert 0.0 < r.pythag_win_pct < 1.0

    def test_save_and_load(self, ratings, tmp_path):
        path = tmp_path / "ratings.json"
        ratings.save_to_file(path)

        rp2 = RatingsProvider()
        assert rp2.load_from_file(path)
        assert rp2.is_loaded

        r = rp2.get("Duke")
        assert r is not None
        assert r.adj_o == 120.0

    def test_load_nonexistent(self):
        rp = RatingsProvider()
        assert not rp.load_from_file("/tmp/nonexistent_ratings.json")

    def test_all_teams(self, ratings):
        teams = ratings.all_teams()
        assert len(teams) == 4


# ---- Normalized name tests ----

class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("Duke") == "duke"

    def test_strips_whitespace(self):
        assert _normalize_name("  Duke  ") == "duke"

    def test_normalizes_state(self):
        assert _normalize_name("Ohio State") == "ohio st"

    def test_normalizes_st_dot(self):
        assert _normalize_name("St. John's") == "st john's"


# ---- build_matchup_fn tests ----

class TestBuildMatchupFn:
    def test_uses_ratings_when_available(self, state, ratings):
        fn = build_matchup_fn(state, ratings)
        # Duke (120o/90d) vs Weak Team (95o/110d) — Duke heavily favored
        prob = fn("Duke", "Weak Team")
        assert prob > 0.85

    def test_uses_alias_for_lookup(self, state, ratings):
        fn = build_matchup_fn(state, ratings)
        # "UConn" in state -> "Connecticut" in ratings via alias
        prob = fn("UConn", "Weak Team")
        assert prob > 0.85

    def test_falls_back_to_seeds(self, state, ratings):
        fn = build_matchup_fn(state, ratings)
        # "Unknown Team" not in ratings, should fall back to seed-based
        prob = fn("Unknown Team", "Other Unknown")
        expected = seed_win_prob(8, 9)
        assert prob == expected

    def test_no_ratings_uses_seeds(self, state):
        fn = build_matchup_fn(state, None)
        prob = fn("Duke", "Weak Team")
        expected = seed_win_prob(1, 16)
        assert prob == expected

    def test_unknown_team_returns_half(self, state):
        fn = build_matchup_fn(state, None)
        prob = fn("Completely Unknown", "Also Unknown")
        assert prob == 0.5

    def test_mixed_availability(self, state, ratings):
        fn = build_matchup_fn(state, ratings)
        # Duke has ratings, Unknown Team doesn't — should fall back to seeds
        prob = fn("Duke", "Unknown Team")
        expected = seed_win_prob(1, 8)
        assert prob == expected
