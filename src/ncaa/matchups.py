"""Pairwise matchup win probability calculations.

Uses the log5 method to convert team strength ratings into head-to-head
win probabilities. The log5 formula was originally proposed by Bill James
for baseball and works well for any sport where you have calibrated
per-team strength estimates.

Also supports efficiency-based probability via the Pythagorean expectation
method used by KenPom/Barttorvik.
"""

from __future__ import annotations

import math

from typing import TYPE_CHECKING

from src.data.models import MatchupProbability, TournamentState

if TYPE_CHECKING:
    from src.ncaa.ratings import RatingsProvider


def log5(p_a: float, p_b: float) -> float:
    """Compute P(A beats B) using the log5 method.

    Given each team's generic win probability against an average opponent:
      P(A beats B) = (p_a - p_a * p_b) / (p_a + p_b - 2 * p_a * p_b)

    Args:
        p_a: Team A's probability of beating an average team (0-1).
        p_b: Team B's probability of beating an average team (0-1).

    Returns:
        P(A beats B), between 0 and 1.
    """
    if p_a <= 0.0:
        return 0.0
    if p_b <= 0.0:
        return 1.0
    if p_a >= 1.0:
        return 1.0
    if p_b >= 1.0:
        return 0.0

    denom = p_a + p_b - 2 * p_a * p_b
    if denom == 0:
        return 0.5
    return (p_a - p_a * p_b) / denom


def efficiency_win_prob(
    adj_o_a: float,
    adj_d_a: float,
    adj_o_b: float,
    adj_d_b: float,
    avg_tempo: float = 68.0,
    home_advantage: float = 0.0,
) -> float:
    """Compute P(A beats B) from Barttorvik/KenPom efficiency ratings.

    Uses the Pythagorean expectation approach:
    1. Estimate each team's scoring margin in a matchup
    2. Convert margin to win probability using a logistic function

    Args:
        adj_o_a: Team A's adjusted offensive efficiency (pts per 100 possessions).
        adj_d_a: Team A's adjusted defensive efficiency.
        adj_o_b: Team B's adjusted offensive efficiency.
        adj_d_b: Team B's adjusted defensive efficiency.
        avg_tempo: D1 average tempo (possessions per game). ~68 for modern NCAA.
        home_advantage: Points to add to team A's margin (0 for neutral site).

    Returns:
        P(A beats B), between 0 and 1.
    """
    # Estimated points per game for each team in this matchup
    # Team A scores: (A's offense vs B's defense) adjusted to per-game
    # avg_efficiency ≈ 100 (D1 average pts per 100 possessions)
    avg_efficiency = 100.0
    pace_factor = avg_tempo / 100.0  # convert from per-100 to per-game

    a_pts = (adj_o_a * adj_d_b / avg_efficiency) * pace_factor
    b_pts = (adj_o_b * adj_d_a / avg_efficiency) * pace_factor

    margin = a_pts - b_pts + home_advantage

    # Convert point spread to win probability using logistic function
    # Empirically, ~11 points ≈ 1 standard deviation in college basketball
    return _margin_to_win_prob(margin)


def _margin_to_win_prob(margin: float, sigma: float = 11.0) -> float:
    """Convert a predicted scoring margin to a win probability.

    Uses a logistic function calibrated to college basketball.
    A margin of 0 → 50%, margin of +11 → ~84%.

    Args:
        margin: Predicted scoring margin (positive = team A favored).
        sigma: Standard deviation of the scoring margin distribution.
            ~11 points for NCAA men's basketball.

    Returns:
        Win probability for team A (0-1).
    """
    return 1.0 / (1.0 + math.exp(-margin * math.log(10) / sigma))


def seed_win_prob(seed_a: int, seed_b: int) -> float:
    """Estimate P(seed_a beats seed_b) from historical seed-vs-seed data.

    Fallback when team-level ratings aren't available. Based on aggregate
    NCAA tournament results since 1985.

    Returns a reasonable estimate, not a precise historical average.
    """
    # Historical first-round upset rates (approximate, 1985-2024)
    # Format: {(high_seed, low_seed): P(high_seed_wins)}
    HISTORICAL_RATES: dict[tuple[int, int], float] = {
        (1, 16): 0.99,
        (2, 15): 0.94,
        (3, 14): 0.85,
        (4, 13): 0.79,
        (5, 12): 0.65,
        (6, 11): 0.63,
        (7, 10): 0.61,
        (8, 9): 0.52,
    }

    if seed_a == seed_b:
        return 0.5

    high = min(seed_a, seed_b)
    low = max(seed_a, seed_b)
    p_high = HISTORICAL_RATES.get((high, low))

    if p_high is not None:
        return p_high if seed_a == high else 1.0 - p_high

    # For matchups not in the R64 table, estimate from seed gap
    # Bigger seed gap → higher win prob for the better seed
    gap = low - high
    p_high_est = 0.5 + gap * 0.03  # ~3% per seed line
    p_high_est = min(p_high_est, 0.95)
    return p_high_est if seed_a == high else 1.0 - p_high_est


def build_matchup_fn(
    state: TournamentState,
    ratings: "RatingsProvider | None" = None,
):
    """Build a matchup function using ratings when available, falling back to seeds.

    Args:
        state: Tournament state with team info (seeds).
        ratings: Optional RatingsProvider with efficiency ratings.

    Returns:
        A callable (team_a, team_b) -> float giving P(A beats B).
    """
    seed_lookup = {t.name: t.seed for t in state.teams}

    def matchup_fn(team_a: str, team_b: str) -> float:
        # Try efficiency-based probability if ratings are available
        if ratings is not None and ratings.is_loaded:
            ra = ratings.get(team_a)
            rb = ratings.get(team_b)
            if ra is not None and rb is not None:
                return efficiency_win_prob(ra.adj_o, ra.adj_d, rb.adj_o, rb.adj_d)

        # Fall back to seed-based probability
        seed_a = seed_lookup.get(team_a)
        seed_b = seed_lookup.get(team_b)
        if seed_a is not None and seed_b is not None:
            return seed_win_prob(seed_a, seed_b)
        return 0.5

    return matchup_fn


def matchup_probability(
    team_a: str,
    team_b: str,
    prob_a_wins: float,
) -> MatchupProbability:
    """Create a MatchupProbability model instance."""
    return MatchupProbability(
        team_a=team_a,
        team_b=team_b,
        prob_a_wins=max(0.0, min(1.0, prob_a_wins)),
    )
