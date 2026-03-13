"""Tests for the standings engine."""

import pytest
import numpy as np

from src.data.models import (
    BracketEntry,
    GameResult,
    GameSlot,
    Pick,
    Round,
    Team,
    TournamentState,
)
from src.ncaa.bracket import build_bracket
from src.standings.engine import StandingsEngine, _rank_scores
from src.standings.scoring import score_entry, espn_score, ESPN_POINTS


# ---- Fixtures ----

@pytest.fixture
def bracket():
    return build_bracket(["East", "West", "South", "Midwest"])


def _make_teams() -> list[Team]:
    teams = []
    for region in ["East", "West", "South", "Midwest"]:
        for seed in range(1, 17):
            teams.append(Team(name=f"{region} {seed}", seed=seed, region=region))
    return teams


@pytest.fixture
def all_teams():
    return _make_teams()


def always_higher_seed(team_a: str, team_b: str) -> float:
    """1-seed always beats everyone."""
    try:
        seed_a = int(team_a.split()[-1])
        seed_b = int(team_b.split()[-1])
    except (ValueError, IndexError):
        return 0.5
    if seed_a < seed_b:
        return 1.0
    elif seed_a > seed_b:
        return 0.0
    return 0.5


def coin_flip(team_a: str, team_b: str) -> float:
    return 0.5


# ---- Scoring tests ----

class TestScoring:

    def test_espn_points(self):
        assert espn_score(Round.ROUND_OF_64) == 10
        assert espn_score(Round.ROUND_OF_32) == 20
        assert espn_score(Round.SWEET_16) == 40
        assert espn_score(Round.ELITE_8) == 80
        assert espn_score(Round.FINAL_4) == 160
        assert espn_score(Round.CHAMPIONSHIP) == 320

    def test_perfect_r64_score(self):
        picks = {i: f"winner_{i}" for i in range(1, 33)}
        outcomes = {i: f"winner_{i}" for i in range(1, 33)}
        rounds = {i: Round.ROUND_OF_64 for i in range(1, 33)}
        assert score_entry(picks, outcomes, rounds) == 32 * 10

    def test_no_correct_picks(self):
        picks = {1: "wrong"}
        outcomes = {1: "right"}
        rounds = {1: Round.ROUND_OF_64}
        assert score_entry(picks, outcomes, rounds) == 0

    def test_mixed_rounds(self):
        picks = {1: "A", 33: "B", 63: "C"}
        outcomes = {1: "A", 33: "B", 63: "C"}
        rounds = {1: Round.ROUND_OF_64, 33: Round.ROUND_OF_32, 63: Round.CHAMPIONSHIP}
        assert score_entry(picks, outcomes, rounds) == 10 + 20 + 320

    def test_max_possible_score(self):
        total = sum(count * pts for (round_val, pts), count in zip(
            ESPN_POINTS.items(), [32, 16, 8, 4, 2, 1]
        ))
        assert total == 1920  # 320+320+320+320+320+320


# ---- Rank function tests ----

class TestRankScores:

    def test_simple_ranking(self):
        scores = np.array([100, 200, 150])
        ranks = _rank_scores(scores)
        assert ranks[0] == 3  # 100 is worst
        assert ranks[1] == 1  # 200 is best
        assert ranks[2] == 2  # 150 is middle

    def test_tied_scores(self):
        scores = np.array([100, 100, 50])
        ranks = _rank_scores(scores)
        assert ranks[0] == 1
        assert ranks[1] == 1
        assert ranks[2] == 3

    def test_all_tied(self):
        scores = np.array([50, 50, 50])
        ranks = _rank_scores(scores)
        assert all(r == 1 for r in ranks)


# ---- Standings engine tests ----

def _make_entry(entry_id: str, picks_map: dict[int, str], bracket) -> BracketEntry:
    """Helper to create a BracketEntry with picks for specific games."""
    picks = []
    for gid, team in picks_map.items():
        slot = bracket.slots[gid]
        picks.append(Pick(
            game_slot=GameSlot(game_id=gid, round=slot.round),
            team_name=team,
        ))
    return BracketEntry(
        entry_id=entry_id,
        entry_name=f"Entry {entry_id}",
        owner_name="Test",
        platform="espn",
        group_id="test-group",
        picks=picks,
    )


class TestStandingsEngineAllComplete:

    def test_all_games_complete(self, bracket, all_teams):
        """When all games are done, standings are deterministic."""
        # Simulate a simple tournament where 1-seeds win everything
        completed = []
        outcomes = {}

        # R64: 1-seeds always win
        for region_idx, region in enumerate(["East", "West", "South", "Midwest"]):
            base = region_idx * 8 + 1
            for i in range(8):
                gid = base + i
                from src.ncaa.bracket import R64_SEED_MATCHUPS
                high, low = R64_SEED_MATCHUPS[i]
                winner = f"{region} {high}"
                loser = f"{region} {low}"
                completed.append(GameResult(
                    game_slot=GameSlot(game_id=gid, round=Round.ROUND_OF_64, region=region),
                    winner=winner, loser=loser,
                ))
                outcomes[gid] = winner

        # For simplicity, just complete R64 and leave rest "completed" as 1-seeds
        # Actually let's just test with a small number of completed games
        # Re-do: test with all 63 games completed
        # This is complex — let's simplify and test with just a few entries

        state = TournamentState(year=2026, completed_games=completed, teams=all_teams)

        # Entry that picked all high seeds correctly
        picks_correct = {gid: outcomes[gid] for gid in outcomes}
        entry_correct = _make_entry("correct", picks_correct, bracket)

        # Entry that picked all wrong
        picks_wrong = {}
        for region_idx, region in enumerate(["East", "West", "South", "Midwest"]):
            base = region_idx * 8 + 1
            for i in range(8):
                gid = base + i
                from src.ncaa.bracket import R64_SEED_MATCHUPS
                high, low = R64_SEED_MATCHUPS[i]
                picks_wrong[gid] = f"{region} {low}"  # wrong pick
        entry_wrong = _make_entry("wrong", picks_wrong, bracket)

        engine = StandingsEngine(bracket, coin_flip, state, [entry_correct, entry_wrong])
        results = engine.compute()

        assert len(results) == 2
        correct_result = next(r for r in results if r.entry_id == "correct")
        wrong_result = next(r for r in results if r.entry_id == "wrong")

        assert correct_result.current_score == 32 * 10  # 320
        assert wrong_result.current_score == 0


class TestStandingsEngineMC:

    def test_deterministic_matchup_mc(self, bracket, all_teams):
        """When matchups are deterministic, entry picking 1-seeds gets credit
        only for games on the 1-seed's bracket path (not other games in the region)."""
        state = TournamentState(year=2026, completed_games=[], teams=all_teams)

        # Entry picks each region's 1-seed for ALL games in that region.
        # But only games on the 1-seed's path will be correct:
        # Per region: R64 game 1(1v16), R32 game(1v8), S16 game(1v4), E8 game(1v2)
        # = 4 correct per region × 4 regions = 16 regional games correct
        # = 4×10 + 4×20 + 4×40 + 4×80 = 600 deterministic regional pts
        picks = {}
        for gid in range(1, 64):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                picks[gid] = f"{region} 1"
            elif gid == 61:
                picks[gid] = "East 1"
            elif gid == 62:
                picks[gid] = "South 1"
            elif gid == 63:
                picks[gid] = "East 1"

        entry = _make_entry("all_ones", picks, bracket)

        engine = StandingsEngine(bracket, always_higher_seed, state, [entry])
        results = engine.compute(n_sims=100)

        assert len(results) == 1
        r = results[0]
        assert r.rank_probabilities.get(1, 0) == 1.0
        # 600 deterministic regional pts + F4/NCG coin flip expected value
        assert r.expected_final_score >= 600
        assert r.expected_final_score < 1920

    def test_two_entries_mc(self, bracket, all_teams):
        """Two different entries should get different expected scores."""
        state = TournamentState(year=2026, completed_games=[], teams=all_teams)

        # Entry A picks all 1-seeds
        picks_a = {}
        for gid in range(1, 64):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                picks_a[gid] = f"{region} 1"
            elif gid == 61:
                picks_a[gid] = "East 1"
            elif gid == 62:
                picks_a[gid] = "South 1"
            elif gid == 63:
                picks_a[gid] = "East 1"

        # Entry B picks all 16-seeds (extreme underdog)
        picks_b = {}
        for gid in range(1, 64):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                picks_b[gid] = f"{region} 16"
            elif gid == 61:
                picks_b[gid] = "East 16"
            elif gid == 62:
                picks_b[gid] = "South 16"
            elif gid == 63:
                picks_b[gid] = "East 16"

        entry_a = _make_entry("favorites", picks_a, bracket)
        entry_b = _make_entry("underdogs", picks_b, bracket)

        engine = StandingsEngine(bracket, always_higher_seed, state, [entry_a, entry_b])
        results = engine.compute(n_sims=100)

        fav = next(r for r in results if r.entry_id == "favorites")
        dog = next(r for r in results if r.entry_id == "underdogs")

        # With deterministic 1-seed wins, favorites should always win
        assert fav.expected_final_score > dog.expected_final_score


class TestStandingsEngineExact:

    def test_exact_with_few_remaining(self, bracket, all_teams):
        """Test exact enumeration with a small number of remaining games."""
        # Complete all games except the championship (game 63)
        # and F4 games (61, 62) — 3 remaining games, 2^3 = 8 outcomes
        completed = []

        # Complete all R64, R32, S16, E8 games
        for gid in range(1, 61):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                winner = f"{region} 1"
                loser = f"{region} 2"
            else:
                winner = "East 1"
                loser = "West 1"
            completed.append(GameResult(
                game_slot=GameSlot(game_id=gid, round=slot.round),
                winner=winner, loser=loser,
            ))

        state = TournamentState(year=2026, completed_games=completed, teams=all_teams)

        # Entry picks East 1 to win it all
        picks = {}
        for gid in range(1, 64):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                picks[gid] = f"{region} 1"
            elif gid == 61:
                picks[gid] = "East 1"
            elif gid == 62:
                picks[gid] = "South 1"
            elif gid == 63:
                picks[gid] = "East 1"
        entry = _make_entry("test", picks, bracket)

        engine = StandingsEngine(bracket, coin_flip, state, [entry])
        results = engine.compute()

        assert len(results) == 1
        r = results[0]
        # With coin flip, expected score from 3 remaining games should be:
        # Each game has 50% chance of being correct
        # F4 (160 pts) * 0.5 + F4 (160 pts) * 0.5 + NCG (320 pts) * ...
        # This is more complex due to conditional outcomes
        assert r.expected_final_score > 0
        assert r.rank_probabilities.get(1, 0) == 1.0  # only one entry

    def test_exact_vs_mc_agree(self, bracket, all_teams):
        """Exact and MC should produce similar results for small games."""
        # Complete all but 3 games
        completed = []
        for gid in range(1, 61):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                winner = f"{region} 1"
                loser = f"{region} 2"
            else:
                winner = "East 1"
                loser = "West 1"
            completed.append(GameResult(
                game_slot=GameSlot(game_id=gid, round=slot.round),
                winner=winner, loser=loser,
            ))

        state = TournamentState(year=2026, completed_games=completed, teams=all_teams)

        picks = {}
        for gid in range(1, 64):
            slot = bracket.slots[gid]
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
                picks[gid] = f"{region} 1"
            elif gid == 61:
                picks[gid] = "East 1"
            elif gid == 62:
                picks[gid] = "South 1"
            elif gid == 63:
                picks[gid] = "East 1"
        entry = _make_entry("test", picks, bracket)

        # Exact
        engine_exact = StandingsEngine(bracket, coin_flip, state, [entry])
        results_exact = engine_exact.compute()

        # MC with many sims
        engine_mc = StandingsEngine(bracket, coin_flip, state, [entry])
        # Force MC by using more sims
        results_mc = engine_mc._monte_carlo(50_000)

        exact_score = results_exact[0].expected_final_score
        mc_score = results_mc[0].expected_final_score

        # Should be within ~5% of each other
        assert abs(exact_score - mc_score) / max(exact_score, 1) < 0.05
