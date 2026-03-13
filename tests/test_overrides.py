"""Tests for the adjustments/overrides module and projections router."""

import pytest
from src.data.models import (
    GameResult,
    GameSlot,
    OverridePayload,
    Round,
    Team,
    TournamentState,
)
from src.ncaa.bracket import build_bracket
from src.adjustments.overrides import apply_locks, find_team_r64_game
from src.projections.engine import ProjectionEngine
from src.ncaa.matchups import seed_win_prob


REGION_NAMES = ["East", "West", "South", "Midwest"]


def _make_teams() -> list[Team]:
    """Create 64 teams across 4 regions."""
    teams = []
    regions = REGION_NAMES
    for region in regions:
        for seed in range(1, 17):
            teams.append(Team(name=f"{region}-{seed}", seed=seed, region=region))
    return teams


def _make_state(teams: list[Team], completed: list[GameResult] | None = None) -> TournamentState:
    return TournamentState(year=2025, teams=teams, completed_games=completed or [])


def _matchup_fn(team_a: str, team_b: str) -> float:
    """Simple seed-based matchup function."""
    seed_a = int(team_a.split("-")[1])
    seed_b = int(team_b.split("-")[1])
    return seed_win_prob(seed_a, seed_b)


class TestFindTeamR64Game:
    def test_1_seed_east(self):
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)
        gid = find_team_r64_game(bracket, state, "East-1")
        # East region is index 0, 1-seed is game offset 0 → game_id 1
        assert gid == 1

    def test_2_seed_east(self):
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)
        gid = find_team_r64_game(bracket, state, "East-2")
        # 2-seed is the 8th matchup (index 7) → game_id 8
        assert gid == 8

    def test_1_seed_west(self):
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)
        gid = find_team_r64_game(bracket, state, "West-1")
        # West region is index 1, base = 9, 1-seed is offset 0 → game_id 9
        assert gid == 9

    def test_unknown_team(self):
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)
        gid = find_team_r64_game(bracket, state, "Unknown-99")
        assert gid is None


class TestApplyLocks:
    def test_lock_r64_game(self):
        """Locking a team at R64 adds a single synthetic game result."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        locks = [OverridePayload.GameLock(game_id=1, winner="East-1")]
        new_state = apply_locks(bracket, state, locks)

        assert new_state.winner_of(1) == "East-1"
        assert len(new_state.completed_games) == 1

    def test_lock_e8_cascades_backward(self):
        """Locking a team at E8 should cascade through R64, R32, S16."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        # Lock East-1 at game 57 (E8 for East region)
        locks = [OverridePayload.GameLock(game_id=57, winner="East-1")]
        new_state = apply_locks(bracket, state, locks)

        # East-1 starts at game 1 (R64)
        # Path: 1 → 33 → 49 → 57
        assert new_state.winner_of(1) == "East-1"
        assert new_state.winner_of(33) == "East-1"
        assert new_state.winner_of(49) == "East-1"
        assert new_state.winner_of(57) == "East-1"
        assert len(new_state.completed_games) == 4

    def test_lock_championship_cascades_full_path(self):
        """Locking a team at championship cascades through entire bracket path."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        locks = [OverridePayload.GameLock(game_id=63, winner="East-1")]
        new_state = apply_locks(bracket, state, locks)

        # Path: 1 → 33 → 49 → 57 → 61 → 63
        assert new_state.winner_of(1) == "East-1"
        assert new_state.winner_of(33) == "East-1"
        assert new_state.winner_of(49) == "East-1"
        assert new_state.winner_of(57) == "East-1"
        assert new_state.winner_of(61) == "East-1"
        assert new_state.winner_of(63) == "East-1"
        assert len(new_state.completed_games) == 6

    def test_lock_skips_already_completed(self):
        """Lock should skip games that are already completed."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()

        # Game 1 is already completed
        existing = [GameResult(
            game_slot=GameSlot(game_id=1, round=Round.ROUND_OF_64, region="East"),
            winner="East-1",
            loser="East-16",
        )]
        state = _make_state(teams, existing)

        locks = [OverridePayload.GameLock(game_id=33, winner="East-1")]
        new_state = apply_locks(bracket, state, locks)

        # Should have original game 1 + new game 33
        assert len(new_state.completed_games) == 2
        assert new_state.winner_of(1) == "East-1"
        assert new_state.winner_of(33) == "East-1"

    def test_empty_locks(self):
        """Empty locks returns same state."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)
        new_state = apply_locks(bracket, state, [])
        assert new_state is state

    def test_multiple_locks(self):
        """Multiple locks for different teams."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        locks = [
            OverridePayload.GameLock(game_id=57, winner="East-1"),  # E8 East
            OverridePayload.GameLock(game_id=58, winner="West-1"),  # E8 West
        ]
        new_state = apply_locks(bracket, state, locks)

        assert new_state.winner_of(57) == "East-1"
        assert new_state.winner_of(58) == "West-1"
        # East path: 1→33→49→57 = 4 games
        # West path: 9→37→51→58 = 4 games
        assert len(new_state.completed_games) == 8


class TestProbOverrides:
    def test_r64_override(self):
        """Probability override changes R64 game result."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        # Without override, 1-seed should dominate 16-seed
        engine = ProjectionEngine(bracket, _matchup_fn, state)
        engine.compute()
        win_probs = engine.get_win_probs(1)
        assert win_probs["East-1"] > 0.9  # 1 vs 16

        # With override: set to coin flip (prob_a_wins=0.5 means 1-seed has 50%)
        engine2 = ProjectionEngine(bracket, _matchup_fn, state, prob_overrides={1: 0.5})
        engine2.compute()
        win_probs2 = engine2.get_win_probs(1)
        assert abs(win_probs2["East-1"] - 0.5) < 0.01
        assert abs(win_probs2["East-16"] - 0.5) < 0.01

    def test_override_affects_later_rounds(self):
        """Overriding an R64 game probability should ripple to later rounds."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        # Baseline: 1-seed very likely to advance
        engine1 = ProjectionEngine(bracket, _matchup_fn, state)
        engine1.compute()
        adv1 = engine1.get_advancement_probs()
        baseline_r32_prob = adv1["East-1"].get(2, 0)  # P(East-1 wins R32)

        # Override: make 16-seed favored in game 1
        engine2 = ProjectionEngine(bracket, _matchup_fn, state, prob_overrides={1: 0.1})
        engine2.compute()
        adv2 = engine2.get_advancement_probs()
        reduced_r32_prob = adv2.get("East-1", {}).get(2, 0)

        assert reduced_r32_prob < baseline_r32_prob

    def test_later_round_override(self):
        """Override on a later-round game changes its probability."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        # Override game 33 (R32, East region): set upper feeder side to 90%
        engine = ProjectionEngine(bracket, _matchup_fn, state, prob_overrides={33: 0.9})
        engine.compute()
        win_probs = engine.get_win_probs(33)

        # The teams from feeder_a (game 1) side should have higher combined win prob
        # than the teams from feeder_b (game 2) side
        # Feeder_a winners: East-1 or East-16
        # Feeder_b winners: East-8 or East-9
        feeder_a_prob = win_probs.get("East-1", 0) + win_probs.get("East-16", 0)
        feeder_b_prob = win_probs.get("East-8", 0) + win_probs.get("East-9", 0)
        assert feeder_a_prob > feeder_b_prob


class TestLocksWithProjectionEngine:
    def test_lock_forces_winner(self):
        """Locking a team should make their win probability 1.0 for that game."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        locks = [OverridePayload.GameLock(game_id=1, winner="East-1")]
        locked_state = apply_locks(bracket, state, locks)

        engine = ProjectionEngine(bracket, _matchup_fn, locked_state)
        results = engine.compute()

        game1 = next(r for r in results if r.game_id == 1)
        assert game1.is_completed
        assert game1.prob_a_wins == 1.0

    def test_lock_e8_forces_advancement(self):
        """Locking team at E8 should give them 100% advancement through earlier rounds."""
        bracket = build_bracket(REGION_NAMES)
        teams = _make_teams()
        state = _make_state(teams)

        locks = [OverridePayload.GameLock(game_id=57, winner="East-1")]
        locked_state = apply_locks(bracket, state, locks)

        engine = ProjectionEngine(bracket, _matchup_fn, locked_state)
        engine.compute()
        adv = engine.get_advancement_probs()

        east_1_probs = adv.get("East-1", {})
        # Should have 100% through R64, R32, S16, E8
        assert east_1_probs.get(1, 0) == 1.0  # R64
        assert east_1_probs.get(2, 0) == 1.0  # R32
        assert east_1_probs.get(3, 0) == 1.0  # S16
        assert east_1_probs.get(4, 0) == 1.0  # E8
