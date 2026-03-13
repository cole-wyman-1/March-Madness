"""Tests for the projection engine."""

import pytest

from src.data.models import (
    GameResult,
    GameSlot,
    Round,
    Team,
    TournamentState,
)
from src.ncaa.bracket import build_bracket
from src.projections.engine import ProjectionEngine


def _make_teams(region_name: str, region_idx: int) -> list[Team]:
    """Create 16 teams for a region."""
    return [
        Team(name=f"{region_name} {seed}", seed=seed, region=region_name)
        for seed in range(1, 17)
    ]


def _make_all_teams(region_names: list[str]) -> list[Team]:
    teams = []
    for name in region_names:
        teams.extend(_make_teams(name, 0))
    return teams


@pytest.fixture
def bracket():
    return build_bracket(["East", "West", "South", "Midwest"])


@pytest.fixture
def all_teams():
    return _make_all_teams(["East", "West", "South", "Midwest"])


@pytest.fixture
def empty_state(all_teams):
    return TournamentState(year=2026, completed_games=[], teams=all_teams)


def equal_matchup(team_a: str, team_b: str) -> float:
    """All matchups are 50/50."""
    return 0.5


def seed_favored_matchup(team_a: str, team_b: str) -> float:
    """Higher seed (lower number) always wins with P=0.75."""
    # Extract seed from team name like "East 1"
    try:
        seed_a = int(team_a.split()[-1])
        seed_b = int(team_b.split()[-1])
    except (ValueError, IndexError):
        return 0.5

    if seed_a < seed_b:
        return 0.75
    elif seed_a > seed_b:
        return 0.25
    return 0.5


class TestProjectionEngineBasics:

    def test_produces_63_results(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, equal_matchup, empty_state)
        results = engine.compute()
        assert len(results) == 63

    def test_all_game_ids_present(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, equal_matchup, empty_state)
        results = engine.compute()
        game_ids = {r.game_id for r in results}
        assert game_ids == set(range(1, 64))

    def test_r64_equal_matchup(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, equal_matchup, empty_state)
        results = engine.compute()

        r64_results = [r for r in results if r.round == Round.ROUND_OF_64]
        assert len(r64_results) == 32

        for r in r64_results:
            assert abs(r.prob_a_wins - 0.5) < 0.01

    def test_r64_seed_favored(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, seed_favored_matchup, empty_state)
        results = engine.compute()

        # Game 1 is 1 vs 16 in East — check via win_probs (order-agnostic)
        win_probs = engine.get_win_probs(1)
        assert win_probs["East 1"] == pytest.approx(0.75)
        assert win_probs["East 16"] == pytest.approx(0.25)

    def test_probabilities_bounded(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, seed_favored_matchup, empty_state)
        results = engine.compute()

        for r in results:
            assert 0.0 <= r.prob_a_wins <= 1.0


class TestProjectionWithCompletedGames:

    def test_completed_game_has_prob_1(self, bracket, all_teams):
        completed = [
            GameResult(
                game_slot=GameSlot(game_id=1, round=Round.ROUND_OF_64, region="East"),
                winner="East 1",
                loser="East 16",
            )
        ]
        state = TournamentState(year=2026, completed_games=completed, teams=all_teams)
        engine = ProjectionEngine(bracket, equal_matchup, state)
        results = engine.compute()

        game_1 = next(r for r in results if r.game_id == 1)
        assert game_1.is_completed
        assert game_1.prob_a_wins == 1.0
        assert game_1.team_a == "East 1"

    def test_completed_game_affects_next_round(self, bracket, all_teams):
        # Complete game 1 (1 vs 16) — 1 seed wins
        # Game 33 is fed by games 1 and 2
        completed = [
            GameResult(
                game_slot=GameSlot(game_id=1, round=Round.ROUND_OF_64, region="East"),
                winner="East 1",
                loser="East 16",
            )
        ]
        state = TournamentState(year=2026, completed_games=completed, teams=all_teams)
        engine = ProjectionEngine(bracket, equal_matchup, state)
        results = engine.compute()

        # Game 33 (R32) should have East 1 as a definite participant
        reach = engine.get_reach_probs(33)
        assert reach.get("East 1") == 1.0


class TestAdvancementProbs:

    def test_1_seed_advances_further(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, seed_favored_matchup, empty_state)
        engine.compute()

        adv = engine.get_advancement_probs()
        # 1 seed should have higher advancement prob than 16 seed
        east_1_probs = adv.get("East 1", {})
        east_16_probs = adv.get("East 16", {})

        # East 1 should have significant R32 advancement prob
        assert east_1_probs.get(2, 0) > east_16_probs.get(2, 0)

    def test_championship_probs_sum_to_1(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, seed_favored_matchup, empty_state)
        engine.compute()

        # All teams' championship win probs should sum to ~1.0
        win_probs = engine.get_win_probs(63)
        total = sum(win_probs.values())
        assert abs(total - 1.0) < 0.01

    def test_reach_probs_r64(self, bracket, empty_state):
        engine = ProjectionEngine(bracket, equal_matchup, empty_state)
        engine.compute()

        # In R64, both teams have reach_prob = 1.0
        reach = engine.get_reach_probs(1)
        assert reach.get("East 1") == 1.0
        assert reach.get("East 16") == 1.0
