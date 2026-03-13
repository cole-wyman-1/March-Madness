"""Tests for matchup probability calculations."""

import pytest
import math

from src.ncaa.matchups import (
    log5,
    efficiency_win_prob,
    seed_win_prob,
    matchup_probability,
    _margin_to_win_prob,
)


class TestLog5:

    def test_equal_teams(self):
        assert log5(0.5, 0.5) == 0.5

    def test_stronger_team_favored(self):
        p = log5(0.8, 0.5)
        assert p > 0.5

    def test_weaker_team_disadvantaged(self):
        p = log5(0.3, 0.7)
        assert p < 0.5

    def test_symmetry(self):
        """P(A beats B) + P(B beats A) = 1."""
        p_ab = log5(0.7, 0.4)
        p_ba = log5(0.4, 0.7)
        assert abs(p_ab + p_ba - 1.0) < 1e-10

    def test_dominant_team(self):
        p = log5(0.95, 0.2)
        assert p > 0.9

    def test_zero_team_always_loses(self):
        assert log5(0.0, 0.5) == 0.0

    def test_perfect_team_always_wins(self):
        assert log5(1.0, 0.5) == 1.0

    def test_both_zero(self):
        # Edge case: both have 0% win rate
        assert log5(0.0, 0.0) == 0.0

    def test_both_perfect(self):
        assert log5(1.0, 1.0) == 1.0

    def test_output_bounded(self):
        """Result should always be between 0 and 1."""
        for p_a in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            for p_b in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
                result = log5(p_a, p_b)
                assert 0.0 <= result <= 1.0


class TestEfficiencyWinProb:

    def test_equal_teams_50_50(self):
        p = efficiency_win_prob(
            adj_o_a=105, adj_d_a=95,
            adj_o_b=105, adj_d_b=95,
        )
        assert abs(p - 0.5) < 0.01

    def test_better_team_favored(self):
        # Team A: great offense + great defense
        # Team B: average
        p = efficiency_win_prob(
            adj_o_a=115, adj_d_a=90,
            adj_o_b=100, adj_d_b=100,
        )
        assert p > 0.7

    def test_home_advantage(self):
        p_neutral = efficiency_win_prob(
            adj_o_a=105, adj_d_a=95,
            adj_o_b=105, adj_d_b=95,
            home_advantage=0.0,
        )
        p_home = efficiency_win_prob(
            adj_o_a=105, adj_d_a=95,
            adj_o_b=105, adj_d_b=95,
            home_advantage=3.5,
        )
        assert p_home > p_neutral

    def test_output_bounded(self):
        p = efficiency_win_prob(
            adj_o_a=130, adj_d_a=80,
            adj_o_b=80, adj_d_b=130,
        )
        assert 0.0 < p < 1.0


class TestMarginToWinProb:

    def test_zero_margin_is_50_50(self):
        assert _margin_to_win_prob(0.0) == 0.5

    def test_positive_margin_above_50(self):
        assert _margin_to_win_prob(5.0) > 0.5

    def test_negative_margin_below_50(self):
        assert _margin_to_win_prob(-5.0) < 0.5

    def test_symmetry(self):
        p_pos = _margin_to_win_prob(7.0)
        p_neg = _margin_to_win_prob(-7.0)
        assert abs(p_pos + p_neg - 1.0) < 1e-10

    def test_large_margin_near_1(self):
        p = _margin_to_win_prob(30.0)
        assert p > 0.95


class TestSeedWinProb:

    def test_1_vs_16(self):
        assert seed_win_prob(1, 16) == 0.99

    def test_16_vs_1(self):
        assert seed_win_prob(16, 1) == pytest.approx(0.01)

    def test_8_vs_9_near_tossup(self):
        p = seed_win_prob(8, 9)
        assert 0.45 < p < 0.55

    def test_same_seed(self):
        assert seed_win_prob(5, 5) == 0.5

    def test_better_seed_favored(self):
        assert seed_win_prob(3, 14) > 0.5
        assert seed_win_prob(14, 3) < 0.5

    def test_non_r64_matchup(self):
        # 1 vs 8 — not in standard R64 matchups, uses gap estimate
        p = seed_win_prob(1, 8)
        assert p > 0.5  # 1 seed should still be favored

    def test_output_bounded(self):
        for a in range(1, 17):
            for b in range(1, 17):
                p = seed_win_prob(a, b)
                assert 0.0 <= p <= 1.0


class TestMatchupProbability:

    def test_creates_model(self):
        mp = matchup_probability("Duke", "UNC", 0.65)
        assert mp.team_a == "Duke"
        assert mp.team_b == "UNC"
        assert mp.prob_a_wins == 0.65
        assert mp.prob_b_wins == pytest.approx(0.35)

    def test_clamps_probability(self):
        mp = matchup_probability("A", "B", 1.5)
        assert mp.prob_a_wins == 1.0

        mp = matchup_probability("A", "B", -0.3)
        assert mp.prob_a_wins == 0.0
