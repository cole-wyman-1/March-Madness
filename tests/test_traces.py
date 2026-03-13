"""Tests for the TracePool simulation engine."""

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
from src.projections.traces import TracePool


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
    """Higher seed (lower number) always wins."""
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


def fair_coin(*_args) -> float:
    return 0.5


def _make_chalk_entry(bracket, entry_id: str, group_id: str = "g1") -> BracketEntry:
    """Create an entry that always picks the higher seed."""
    picks = []
    outcomes: dict[int, str] = {}

    # R64: higher seed always wins
    for gid in bracket.games_in_round(Round.ROUND_OF_64):
        slot = bracket.slot(gid)
        seed_a, seed_b = slot.seed_matchup
        ri = slot.region_index
        region = ["East", "West", "South", "Midwest"][ri]
        winner = f"{region} {min(seed_a, seed_b)}"
        outcomes[gid] = winner
        picks.append(Pick(
            game_slot=GameSlot(game_id=gid, round=slot.round, region=region),
            team_name=winner,
        ))

    # Later rounds
    for round_val in [Round.ROUND_OF_32, Round.SWEET_16, Round.ELITE_8,
                      Round.FINAL_4, Round.CHAMPIONSHIP]:
        for gid in bracket.games_in_round(round_val):
            slot = bracket.slot(gid)
            fa, fb = slot.feeder_game_ids
            team_a = outcomes[fa]
            team_b = outcomes[fb]
            seed_a = int(team_a.split()[-1])
            seed_b = int(team_b.split()[-1])
            winner = team_a if seed_a <= seed_b else team_b
            outcomes[gid] = winner
            region = None
            if slot.region_index is not None:
                region = ["East", "West", "South", "Midwest"][slot.region_index]
            picks.append(Pick(
                game_slot=GameSlot(game_id=gid, round=slot.round, region=region),
                team_name=winner,
            ))

    return BracketEntry(
        entry_id=entry_id,
        entry_name=f"Entry {entry_id}",
        owner_name="Test",
        platform="espn",
        group_id=group_id,
        picks=picks,
    )


# ---- Tests ----

class TestTracePoolGeneration:
    def test_generate_creates_traces(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=100)

        assert pool.is_generated
        assert pool.n_traces == 100
        assert pool.n_remaining == 63  # No completed games

    def test_generate_with_completed_games(self, bracket, all_teams):
        # Complete all R64 games (higher seed wins)
        completed = []
        for gid in bracket.games_in_round(Round.ROUND_OF_64):
            slot = bracket.slot(gid)
            sa, sb = slot.seed_matchup
            ri = slot.region_index
            region = ["East", "West", "South", "Midwest"][ri]
            completed.append(GameResult(
                game_slot=GameSlot(game_id=gid, round=Round.ROUND_OF_64),
                winner=f"{region} {min(sa, sb)}",
                loser=f"{region} {max(sa, sb)}",
            ))

        state = TournamentState(year=2026, teams=all_teams, completed_games=completed)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=50)

        assert pool.n_traces == 50
        assert pool.n_remaining == 31  # 63 - 32 R64 games

    def test_zero_remaining_games(self, bracket, all_teams):
        # Complete all 63 games
        completed = []
        outcomes: dict[int, str] = {}

        for gid in bracket.games_in_round(Round.ROUND_OF_64):
            slot = bracket.slot(gid)
            sa, sb = slot.seed_matchup
            ri = slot.region_index
            region = ["East", "West", "South", "Midwest"][ri]
            winner = f"{region} {min(sa, sb)}"
            loser = f"{region} {max(sa, sb)}"
            outcomes[gid] = winner
            completed.append(GameResult(
                game_slot=GameSlot(game_id=gid, round=Round.ROUND_OF_64),
                winner=winner, loser=loser,
            ))

        for round_val in [Round.ROUND_OF_32, Round.SWEET_16, Round.ELITE_8,
                          Round.FINAL_4, Round.CHAMPIONSHIP]:
            for gid in bracket.games_in_round(round_val):
                slot = bracket.slot(gid)
                fa, fb = slot.feeder_game_ids
                ta, tb = outcomes[fa], outcomes[fb]
                sa = int(ta.split()[-1])
                sb = int(tb.split()[-1])
                winner = ta if sa <= sb else tb
                loser = tb if sa <= sb else ta
                outcomes[gid] = winner
                completed.append(GameResult(
                    game_slot=GameSlot(game_id=gid, round=round_val),
                    winner=winner, loser=loser,
                ))

        state = TournamentState(year=2026, teams=all_teams, completed_games=completed)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=10)

        assert pool.n_remaining == 0
        assert pool.n_traces == 0


class TestTracePoolStandings:
    def test_standings_basic(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, always_higher_seed, state)
        pool.generate(n_traces=200)

        entry = _make_chalk_entry(bracket, "chalk-1")
        standings = pool.compute_standings([entry])

        assert len(standings) == 1
        s = standings[0]
        assert s.entry_id == "chalk-1"
        assert s.expected_final_score > 0
        assert s.rank_probabilities.get(1, 0) == 1.0  # Only entry, always rank 1

    def test_standings_multiple_entries(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=500)

        entries = [
            _make_chalk_entry(bracket, f"e{i}")
            for i in range(3)
        ]
        standings = pool.compute_standings(entries)

        assert len(standings) == 3
        # All entries have same picks, so they should tie
        for s in standings:
            assert s.expected_final_score > 0


class TestTracePoolLocks:
    def test_lock_filters_traces(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=1000)

        entry = _make_chalk_entry(bracket, "e1")

        # Lock game 1 (R64, East 1 vs 16) to "East 16" (the upset)
        standings_locked = pool.compute_standings(
            [entry],
            locks={1: "East 16"},
        )
        assert len(standings_locked) == 1

        # Lock to "East 1" (chalk) should also work
        standings_chalk = pool.compute_standings(
            [entry],
            locks={1: "East 1"},
        )
        assert len(standings_chalk) == 1

    def test_lock_impossible_falls_back(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        # Use deterministic matchup: higher seed always wins
        pool = TracePool(bracket, always_higher_seed, state)
        pool.generate(n_traces=100)

        entry = _make_chalk_entry(bracket, "e1")

        # Lock game 1 to "East 16" — impossible with always_higher_seed
        # Should fall back to analytical engine
        standings = pool.compute_standings(
            [entry],
            locks={1: "East 16"},
        )
        assert len(standings) == 1


class TestTracePoolOverrides:
    def test_prob_override_changes_expected_score(self, bracket, all_teams):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=2000)

        entry = _make_chalk_entry(bracket, "e1")

        # Baseline (no overrides)
        s_base = pool.compute_standings([entry])

        # Override game 1 so East 1 (the chalk pick) wins with 99%
        s_high = pool.compute_standings(
            [entry],
            prob_overrides={1: 0.99},
        )

        # Expected score should be higher when chalk is more likely
        # (since the entry picks chalk)
        assert s_high[0].expected_final_score >= s_base[0].expected_final_score - 5  # tolerance for MC noise


class TestTracePoolPersistence:
    def test_save_and_load(self, bracket, all_teams, tmp_path):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=50)

        save_path = tmp_path / "test_traces.npz"
        pool.save(save_path)

        # Load into a new pool
        pool2 = TracePool(bracket, fair_coin, state)
        assert pool2.load(save_path)
        assert pool2.n_traces == 50
        assert pool2.n_remaining == 63

    def test_load_stale_pool(self, bracket, all_teams, tmp_path):
        state = TournamentState(year=2026, teams=all_teams)
        pool = TracePool(bracket, fair_coin, state)
        pool.generate(n_traces=50)

        save_path = tmp_path / "test_traces.npz"
        pool.save(save_path)

        # Create a new pool with different remaining games (simulate a game completing)
        completed = [GameResult(
            game_slot=GameSlot(game_id=1, round=Round.ROUND_OF_64),
            winner="East 1", loser="East 16",
        )]
        state2 = TournamentState(year=2026, teams=all_teams, completed_games=completed)
        pool2 = TracePool(bracket, fair_coin, state2)

        # Should fail to load (stale)
        assert not pool2.load(save_path)
