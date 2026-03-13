"""Standings engine — Monte Carlo simulation + exact enumeration.

Computes finish probability distributions for each bracket entry:
- P(1st), P(2nd), P(3rd), etc.
- Expected final score
- Current score from completed games

Strategy:
- 32+ remaining games: Monte Carlo with 10,000 simulations
- 15 or fewer remaining games (Sweet 16 onward): Exact enumeration of
  all 2^N outcomes, weighted by probability product. No sampling error.
"""

from __future__ import annotations

import numpy as np
from typing import Callable

from src.data.models import (
    BracketEntry,
    Round,
    StandingsResult,
    TournamentState,
)
from src.ncaa.bracket import Bracket
from src.standings.scoring import score_entry

# Type alias for matchup probability function
MatchupFn = Callable[[str, str], float]

MC_SIMULATIONS = 10_000
EXACT_THRESHOLD = 15  # Use exact enumeration when this many or fewer games remain


class StandingsEngine:
    """Compute finish probability distributions for bracket entries.

    Args:
        bracket: 63-game bracket topology.
        matchup_fn: P(team_a beats team_b) for any pair.
        state: Current tournament state (completed games).
        entries: All bracket entries in the group.
    """

    def __init__(
        self,
        bracket: Bracket,
        matchup_fn: MatchupFn,
        state: TournamentState,
        entries: list[BracketEntry],
        prob_overrides: dict[int, float] | None = None,
    ):
        self.bracket = bracket
        self.matchup_fn = matchup_fn
        self.state = state
        self.entries = entries
        self._prob_overrides: dict[int, float] = prob_overrides or {}

        # Pre-compute game round lookup
        self._game_rounds: dict[int, Round] = {
            gid: slot.round for gid, slot in bracket.slots.items()
        }

        # Completed game outcomes
        self._completed: dict[int, str] = {}
        for g in state.completed_games:
            self._completed[g.game_slot.game_id] = g.winner

        # Remaining games in round order
        completed_ids = state.completed_game_ids
        self._remaining: list[int] = sorted(
            [gid for gid in bracket.slots if gid not in completed_ids],
            key=lambda gid: (bracket.slot(gid).round.value, gid),
        )

        # Pre-extract picks for each entry: {game_id: team_name}
        self._entry_picks: list[dict[int, str]] = [
            e.pick_by_game for e in entries
        ]

        # Current scores from completed games
        self._current_scores: list[int] = [
            score_entry(picks, self._completed, self._game_rounds)
            for picks in self._entry_picks
        ]

    def compute(self, n_sims: int | None = None) -> list[StandingsResult]:
        """Run the full standings computation.

        Args:
            n_sims: Override number of MC simulations (default: MC_SIMULATIONS).

        Returns:
            StandingsResult for each entry.
        """
        n_remaining = len(self._remaining)

        if n_remaining == 0:
            return self._final_standings()

        if n_remaining <= EXACT_THRESHOLD:
            return self._exact_enumeration()
        else:
            return self._monte_carlo(n_sims or MC_SIMULATIONS)

    def _final_standings(self) -> list[StandingsResult]:
        """All games complete — deterministic final standings."""
        scores = np.array(self._current_scores, dtype=np.float64)
        n = len(self.entries)

        # Rank: 1 = highest score
        ranks = _rank_scores(scores)

        results = []
        for i, entry in enumerate(self.entries):
            rank_probs = {int(ranks[i]): 1.0}
            rank = int(ranks[i])
            results.append(StandingsResult(
                entry_id=entry.entry_id,
                entry_name=entry.entry_name,
                current_score=self._current_scores[i],
                expected_final_score=float(scores[i]),
                rank_probabilities=rank_probs,
                top_3_prob=1.0 if rank <= 3 else 0.0,
                top_5_prob=1.0 if rank <= 5 else 0.0,
            ))
        return results

    def _monte_carlo(self, n_sims: int) -> list[StandingsResult]:
        """Monte Carlo simulation for standings.

        For each simulation:
        1. Simulate all remaining games (round by round, using feeder winners)
        2. Score all entries against the simulated outcomes
        3. Rank entries and record finishing positions
        """
        n_entries = len(self.entries)
        rng = np.random.default_rng()

        # Accumulators
        total_scores = np.zeros(n_entries, dtype=np.float64)
        rank_counts = np.zeros((n_entries, n_entries), dtype=np.int32)  # [entry][rank-1]

        for _ in range(n_sims):
            # Simulate remaining games
            sim_outcomes = dict(self._completed)
            self._simulate_remaining(sim_outcomes, rng)

            # Score all entries
            scores = np.array([
                score_entry(picks, sim_outcomes, self._game_rounds)
                for picks in self._entry_picks
            ], dtype=np.float64)

            total_scores += scores

            # Rank and record
            ranks = _rank_scores(scores)
            for i, rank in enumerate(ranks):
                rank_counts[i, int(rank) - 1] += 1

        return self._build_results(total_scores / n_sims, rank_counts, n_sims)

    def _exact_enumeration(self) -> list[StandingsResult]:
        """Exact enumeration of all 2^N possible remaining outcomes.

        Each outcome is weighted by the product of individual game probabilities.
        Only feasible when N ≤ ~15 games remain.
        """
        n_remaining = len(self._remaining)
        n_entries = len(self.entries)
        n_outcomes = 2 ** n_remaining

        # Accumulators (weighted)
        weighted_scores = np.zeros(n_entries, dtype=np.float64)
        weighted_rank_probs = np.zeros((n_entries, n_entries), dtype=np.float64)

        for outcome_bits in range(n_outcomes):
            # Simulate this specific outcome
            sim_outcomes = dict(self._completed)
            weight = self._enumerate_outcome(sim_outcomes, outcome_bits)

            if weight <= 0:
                continue

            # Score all entries
            scores = np.array([
                score_entry(picks, sim_outcomes, self._game_rounds)
                for picks in self._entry_picks
            ], dtype=np.float64)

            weighted_scores += weight * scores

            # Rank and accumulate weighted rank probabilities
            ranks = _rank_scores(scores)
            for i, rank in enumerate(ranks):
                weighted_rank_probs[i, int(rank) - 1] += weight

        return self._build_results(weighted_scores, weighted_rank_probs, 1.0)

    def _simulate_remaining(
        self, outcomes: dict[int, str], rng: np.random.Generator
    ) -> None:
        """Simulate all remaining games, filling in outcomes dict.

        Games are processed in round order so feeder winners are available.
        """
        for gid in self._remaining:
            team_a, team_b = self._get_matchup(gid, outcomes)
            if team_a is None or team_b is None:
                continue

            p_a = self._prob_overrides.get(gid, self.matchup_fn(team_a, team_b))
            winner = team_a if rng.random() < p_a else team_b
            outcomes[gid] = winner

    def _enumerate_outcome(
        self, outcomes: dict[int, str], outcome_bits: int
    ) -> float:
        """Play out one specific enumerated outcome and return its probability weight.

        Each bit in outcome_bits determines which team wins each remaining game
        (0 = team_a wins, 1 = team_b wins).
        """
        weight = 1.0

        for i, gid in enumerate(self._remaining):
            team_a, team_b = self._get_matchup(gid, outcomes)
            if team_a is None or team_b is None:
                return 0.0

            p_a = self._prob_overrides.get(gid, self.matchup_fn(team_a, team_b))
            bit = (outcome_bits >> i) & 1

            if bit == 0:
                outcomes[gid] = team_a
                weight *= p_a
            else:
                outcomes[gid] = team_b
                weight *= (1.0 - p_a)

        return weight

    def _get_matchup(
        self, game_id: int, outcomes: dict[int, str]
    ) -> tuple[str | None, str | None]:
        """Determine the two teams playing in a game based on current outcomes.

        For R64: uses bracket seed/region info.
        For later rounds: looks up winners of feeder games in outcomes dict.
        """
        slot = self.bracket.slot(game_id)

        if slot.is_r64:
            seed_a, seed_b = slot.seed_matchup
            team_a = self._find_team(seed_a, slot.region_index)
            team_b = self._find_team(seed_b, slot.region_index)
            return team_a, team_b

        feeder_a, feeder_b = slot.feeder_game_ids
        team_a = outcomes.get(feeder_a)
        team_b = outcomes.get(feeder_b)
        return team_a, team_b

    def _find_team(self, seed: int, region_index: int | None) -> str | None:
        """Find team by seed and region."""
        if region_index is None:
            return None

        region_name = self.bracket.region_names[region_index]
        for t in self.state.teams:
            if t.seed == seed and t.region == region_name:
                return t.name

        # Fallback: try region index as string
        region_str = str(region_index)
        for t in self.state.teams:
            if t.seed == seed and t.region == region_str:
                return t.name

        return None

    def _build_results(
        self,
        expected_scores: np.ndarray,
        rank_data: np.ndarray,
        normalizer: float,
    ) -> list[StandingsResult]:
        """Build StandingsResult list from accumulated data.

        Args:
            expected_scores: Expected final scores per entry.
            rank_data: rank_data[i][r] = count or weighted prob of entry i at rank r+1.
            normalizer: Total weight (n_sims for MC, 1.0 for exact).
        """
        results = []
        for i, entry in enumerate(self.entries):
            rank_probs = {}
            for r in range(len(self.entries)):
                p = float(rank_data[i, r]) / normalizer if normalizer > 0 else 0
                if p > 0:
                    rank_probs[r + 1] = round(p, 6)

            top_3 = sum(rank_probs.get(r, 0) for r in range(1, 4))
            top_5 = sum(rank_probs.get(r, 0) for r in range(1, 6))

            results.append(StandingsResult(
                entry_id=entry.entry_id,
                entry_name=entry.entry_name,
                current_score=self._current_scores[i],
                expected_final_score=round(float(expected_scores[i]), 1),
                rank_probabilities=rank_probs,
                top_3_prob=round(top_3, 6),
                top_5_prob=round(top_5, 6),
            ))

        return results


def _rank_scores(scores: np.ndarray) -> np.ndarray:
    """Rank scores descending (1 = best). Ties get the same rank."""
    n = len(scores)
    order = np.argsort(-scores)  # descending
    ranks = np.empty(n, dtype=np.int32)
    rank = 1
    for i, idx in enumerate(order):
        if i > 0 and scores[order[i]] < scores[order[i - 1]]:
            rank = i + 1
        ranks[idx] = rank
    return ranks
