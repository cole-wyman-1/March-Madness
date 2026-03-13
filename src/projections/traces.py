"""Trace pool — pre-computed tournament simulations for instant what-if analysis.

Instead of re-running 10k MC simulations on every user interaction, we pre-compute
a large pool of tournament traces (full bracket outcomes). User actions then become
cheap array operations:
  - Lock a team → filter traces where that team advances
  - Override probability → importance-weight traces
  - Compute standings → score entries against filtered/weighted traces

Trace format:
  winners: np.ndarray of shape (n_traces, n_remaining_games), dtype=uint8
    Each cell is an index (0 or 1) indicating which side won.
    0 = feeder_a side, 1 = feeder_b side.
  team_names: np.ndarray of shape (n_remaining_games, 2), dtype=object
    For each remaining game, the two team names (from feeder_a, feeder_b).
    For R64, these are fixed; for later rounds, they depend on the trace.
  outcome_teams: np.ndarray of shape (n_traces, n_remaining_games), dtype=object
    The actual team name that won each game in each trace.

Scoring:
  For each trace, we know all 63 game outcomes (completed + simulated).
  We pre-compute a score matrix: scores[trace_idx, entry_idx] = total points.
  Rankings and probabilities are then weighted aggregations over traces.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np

from src.data.models import BracketEntry, Round, StandingsResult, TournamentState
from src.ncaa.bracket import Bracket
from src.standings.scoring import score_entry

logger = logging.getLogger(__name__)

MatchupFn = Callable[[str, str], float]

DEFAULT_N_TRACES = 100_000  # 100k default; user can override
MIN_TRACES_FOR_VALIDITY = 500  # fallback to analytical if fewer traces survive


class TracePool:
    """Pre-computed tournament simulation traces.

    Usage:
        pool = TracePool(bracket, matchup_fn, state)
        pool.generate(n_traces=100_000)

        # Score entries
        standings = pool.compute_standings(entries)

        # What-if: lock a team, override a probability
        standings = pool.compute_standings(
            entries,
            locks={63: "Duke"},              # game_id -> winner
            prob_overrides={57: 0.8},         # game_id -> P(feeder_a wins)
        )
    """

    def __init__(
        self,
        bracket: Bracket,
        matchup_fn: MatchupFn,
        state: TournamentState,
    ):
        self.bracket = bracket
        self.matchup_fn = matchup_fn
        self.state = state

        # Pre-compute completed outcomes and remaining games
        self._completed: dict[int, str] = {
            g.game_slot.game_id: g.winner for g in state.completed_games
        }
        self._game_rounds: dict[int, Round] = {
            gid: slot.round for gid, slot in bracket.slots.items()
        }

        completed_ids = state.completed_game_ids
        self._remaining: list[int] = sorted(
            [gid for gid in bracket.slots if gid not in completed_ids],
            key=lambda gid: (bracket.slot(gid).round.value, gid),
        )

        # Team lookup
        self._teams_by_region: dict[tuple[int, int], str] = {}
        for t in state.teams:
            for ri, rn in enumerate(bracket.region_names):
                if t.region == rn or t.region == str(ri):
                    self._teams_by_region[(t.seed, ri)] = t.name

        # Trace data (populated by generate())
        self._n_traces: int = 0
        self._outcome_teams: np.ndarray | None = None  # (n_traces, n_remaining)
        self._baseline_probs: np.ndarray | None = None  # (n_traces, n_remaining)
        self._game_id_to_col: dict[int, int] = {}

    @property
    def n_traces(self) -> int:
        return self._n_traces

    @property
    def n_remaining(self) -> int:
        return len(self._remaining)

    @property
    def is_generated(self) -> bool:
        return self._outcome_teams is not None

    def generate(self, n_traces: int = DEFAULT_N_TRACES) -> None:
        """Generate the trace pool by simulating n_traces full tournament outcomes."""
        n_rem = len(self._remaining)
        if n_rem == 0:
            self._n_traces = 0
            return

        self._n_traces = n_traces
        self._game_id_to_col = {gid: i for i, gid in enumerate(self._remaining)}

        # outcome_teams[t, g] = team name that won game g in trace t
        outcome_teams = np.empty((n_traces, n_rem), dtype=object)
        # baseline_probs[t, g] = P(winner won) under baseline matchup_fn
        baseline_probs = np.ones((n_traces, n_rem), dtype=np.float64)

        rng = np.random.default_rng()

        for t in range(n_traces):
            outcomes = dict(self._completed)
            for col, gid in enumerate(self._remaining):
                team_a, team_b = self._get_matchup(gid, outcomes)
                if team_a is None or team_b is None:
                    outcome_teams[t, col] = ""
                    baseline_probs[t, col] = 1.0
                    continue

                p_a = self.matchup_fn(team_a, team_b)
                if rng.random() < p_a:
                    outcomes[gid] = team_a
                    outcome_teams[t, col] = team_a
                    baseline_probs[t, col] = p_a
                else:
                    outcomes[gid] = team_b
                    outcome_teams[t, col] = team_b
                    baseline_probs[t, col] = 1.0 - p_a

        self._outcome_teams = outcome_teams
        self._baseline_probs = baseline_probs

        logger.info(
            "Generated %d traces for %d remaining games", n_traces, n_rem
        )

    def compute_standings(
        self,
        entries: list[BracketEntry],
        locks: dict[int, str] | None = None,
        prob_overrides: dict[int, float] | None = None,
    ) -> list[StandingsResult]:
        """Compute standings using the trace pool with optional locks/overrides.

        Args:
            entries: Bracket entries to rank.
            locks: {game_id: winner_team} — filter traces to those where team wins.
            prob_overrides: {game_id: P(feeder_a_side_wins)} — importance-weight traces.

        Returns:
            StandingsResult for each entry.
        """
        if not self.is_generated or self._n_traces == 0:
            return self._fallback_standings(entries, prob_overrides)

        locks = locks or {}
        prob_overrides = prob_overrides or {}

        # Step 1: Filter by locks
        mask = self._compute_lock_mask(locks)
        n_valid = int(np.sum(mask))

        if n_valid < MIN_TRACES_FOR_VALIDITY:
            logger.info(
                "Only %d traces survive filtering (need %d), falling back",
                n_valid, MIN_TRACES_FOR_VALIDITY,
            )
            return self._fallback_standings(entries, prob_overrides, locks)

        # Step 2: Compute importance weights for prob overrides
        weights = self._compute_importance_weights(prob_overrides, mask)

        # Step 3: Score all entries against all valid traces
        scores = self._score_entries(entries, mask)

        # Step 4: Compute weighted standings
        return self._weighted_standings(entries, scores, weights, mask)

    def _compute_lock_mask(self, locks: dict[int, str]) -> np.ndarray:
        """Return boolean mask of traces consistent with all locks."""
        mask = np.ones(self._n_traces, dtype=bool)

        for game_id, required_winner in locks.items():
            col = self._game_id_to_col.get(game_id)
            if col is None:
                # Game already completed — check if lock is consistent
                actual = self._completed.get(game_id)
                if actual and actual != required_winner:
                    mask[:] = False
                    return mask
                continue

            # Filter: only keep traces where this team won this game
            game_winners = self._outcome_teams[:, col]
            mask &= (game_winners == required_winner)

        return mask

    def _compute_importance_weights(
        self,
        prob_overrides: dict[int, float],
        mask: np.ndarray,
    ) -> np.ndarray:
        """Compute importance sampling weights for probability overrides.

        For each override (game_id, user_prob):
          weight *= user_prob / baseline_prob  (if feeder_a side won in trace)
          weight *= (1 - user_prob) / (1 - baseline_prob)  (if feeder_b side won)
        """
        weights = np.ones(self._n_traces, dtype=np.float64)

        for game_id, user_prob in prob_overrides.items():
            col = self._game_id_to_col.get(game_id)
            if col is None:
                continue  # Completed game, no reweighting needed

            # Determine which side each team is on
            # We need to know who feeder_a's winner was vs feeder_b's winner
            # baseline_probs stores P(actual winner won), but we need to know
            # if the winner came from feeder_a or feeder_b.
            slot = self.bracket.slot(game_id)
            if slot.is_r64:
                # R64: team_a = higher seed, straightforward
                # baseline already reflects P(winner), user_prob is P(team_a wins)
                # We need to figure out if the winner IS team_a
                self._apply_r64_weight(col, user_prob, weights, mask)
            else:
                self._apply_later_round_weight(col, game_id, user_prob, weights, mask)

        return weights

    def _apply_r64_weight(
        self, col: int, user_prob: float, weights: np.ndarray, mask: np.ndarray
    ) -> None:
        """Apply importance weight for an R64 game override."""
        gid = self._remaining[col]
        slot = self.bracket.slot(gid)
        seed_a, seed_b = slot.seed_matchup
        team_a = self._teams_by_region.get((seed_a, slot.region_index))

        if team_a is None:
            return

        winners = self._outcome_teams[:, col]
        baseline = self._baseline_probs[:, col]

        a_won = (winners == team_a)
        # Where A won: weight *= user_prob / baseline_prob_a
        # Where B won: weight *= (1 - user_prob) / (1 - baseline_prob_a)
        # baseline stores P(winner won), so for A winners: baseline = P(A),
        # for B winners: baseline = P(B) = 1 - P(A)
        # Therefore baseline_prob_a = baseline where A won, = 1-baseline where B won

        safe_baseline = np.clip(baseline, 1e-10, 1 - 1e-10)
        user_prob = np.clip(user_prob, 1e-10, 1 - 1e-10)

        # Indices where mask is true
        idx = np.where(mask)[0]
        for i in idx:
            if a_won[i]:
                weights[i] *= user_prob / safe_baseline[i]
            else:
                weights[i] *= (1 - user_prob) / safe_baseline[i]

    def _apply_later_round_weight(
        self, col: int, game_id: int, user_prob: float, weights: np.ndarray,
        mask: np.ndarray
    ) -> None:
        """Apply importance weight for a later-round game override.

        user_prob = P(feeder_a side wins).
        """
        slot = self.bracket.slot(game_id)
        feeder_a, feeder_b = slot.feeder_game_ids

        # For each trace, determine if the winner came from feeder_a or feeder_b
        col_a = self._game_id_to_col.get(feeder_a)
        col_b = self._game_id_to_col.get(feeder_b)

        winners = self._outcome_teams[:, col]
        baseline = self._baseline_probs[:, col]

        safe_baseline = np.clip(baseline, 1e-10, 1 - 1e-10)
        user_prob = np.clip(user_prob, 1e-10, 1 - 1e-10)

        # Determine feeder_a winners for each trace
        # If feeder_a is completed, the feeder_a winner is known
        # If feeder_a is in remaining games, look it up from outcome_teams
        feeder_a_winner = self._get_trace_winners(feeder_a)

        idx = np.where(mask)[0]
        for i in idx:
            winner = winners[i]
            fa_winner = feeder_a_winner[i] if isinstance(feeder_a_winner, np.ndarray) else feeder_a_winner
            from_a = (winner == fa_winner)

            if from_a:
                # feeder_a side won; baseline had P(this team won)
                # user wants P(feeder_a side) = user_prob
                # baseline P(feeder_a side) is baked into baseline_probs
                weights[i] *= user_prob / safe_baseline[i]
            else:
                weights[i] *= (1 - user_prob) / safe_baseline[i]

    def _get_trace_winners(self, game_id: int) -> np.ndarray | str:
        """Get the winner of a game across all traces.

        Returns np.ndarray of shape (n_traces,) for remaining games,
        or a single string for completed games.
        """
        if game_id in self._completed:
            return self._completed[game_id]

        col = self._game_id_to_col.get(game_id)
        if col is not None:
            return self._outcome_teams[:, col]

        return ""

    def _score_entries(
        self, entries: list[BracketEntry], mask: np.ndarray
    ) -> np.ndarray:
        """Score all entries against all valid traces.

        Returns: scores[trace_idx, entry_idx] (only for masked traces).
        """
        entry_picks = [e.pick_by_game for e in entries]
        valid_indices = np.where(mask)[0]
        n_valid = len(valid_indices)
        n_entries = len(entries)

        scores = np.zeros((n_valid, n_entries), dtype=np.int32)

        for vi, trace_idx in enumerate(valid_indices):
            # Build full outcome dict for this trace
            outcomes = dict(self._completed)
            for col, gid in enumerate(self._remaining):
                winner = self._outcome_teams[trace_idx, col]
                if winner:
                    outcomes[gid] = winner

            # Score each entry
            for ei, picks in enumerate(entry_picks):
                scores[vi, ei] = score_entry(picks, outcomes, self._game_rounds)

        return scores

    def _weighted_standings(
        self,
        entries: list[BracketEntry],
        scores: np.ndarray,
        weights: np.ndarray,
        mask: np.ndarray,
    ) -> list[StandingsResult]:
        """Compute standings from scored traces with importance weights.

        Args:
            scores: (n_valid, n_entries) score matrix.
            weights: (n_traces,) importance weights.
            mask: (n_traces,) boolean mask.
        """
        valid_indices = np.where(mask)[0]
        valid_weights = weights[valid_indices]

        # Normalize weights
        total_weight = np.sum(valid_weights)
        if total_weight <= 0:
            total_weight = 1.0
        norm_weights = valid_weights / total_weight

        n_entries = len(entries)

        # Weighted expected scores
        expected_scores = np.sum(scores * norm_weights[:, np.newaxis], axis=0)

        # Current scores (from completed games)
        current_scores = []
        for e in entries:
            current_scores.append(
                score_entry(e.pick_by_game, self._completed, self._game_rounds)
            )

        # Weighted rank probabilities
        rank_probs = np.zeros((n_entries, n_entries), dtype=np.float64)
        for vi in range(len(valid_indices)):
            trace_scores = scores[vi, :]
            ranks = _rank_scores(trace_scores)
            w = norm_weights[vi]
            for ei, rank in enumerate(ranks):
                rank_probs[ei, int(rank) - 1] += w

        # Build results
        results = []
        for i, entry in enumerate(entries):
            rp = {}
            for r in range(n_entries):
                p = float(rank_probs[i, r])
                if p > 0.0001:
                    rp[r + 1] = round(p, 6)

            top_3 = sum(rp.get(r, 0) for r in range(1, 4))
            top_5 = sum(rp.get(r, 0) for r in range(1, 6))

            results.append(StandingsResult(
                entry_id=entry.entry_id,
                entry_name=entry.entry_name,
                current_score=current_scores[i],
                expected_final_score=round(float(expected_scores[i]), 1),
                rank_probabilities=rp,
                top_3_prob=round(top_3, 6),
                top_5_prob=round(top_5, 6),
            ))

        return results

    def _fallback_standings(
        self,
        entries: list[BracketEntry],
        prob_overrides: dict[int, float] | None = None,
        locks: dict[int, str] | None = None,
    ) -> list[StandingsResult]:
        """Fall back to the original StandingsEngine when trace pool is insufficient."""
        from src.standings.engine import StandingsEngine
        from src.adjustments.overrides import apply_locks

        state = self.state
        if locks:
            from src.data.models import OverridePayload
            lock_list = [
                OverridePayload.GameLock(game_id=gid, winner=w)
                for gid, w in locks.items()
            ]
            state = apply_locks(self.bracket, state, lock_list)

        engine = StandingsEngine(
            self.bracket, self.matchup_fn, state, entries,
            prob_overrides=prob_overrides,
        )
        return engine.compute()

    def _get_matchup(
        self, game_id: int, outcomes: dict[int, str]
    ) -> tuple[str | None, str | None]:
        """Determine the two teams playing in a game."""
        slot = self.bracket.slot(game_id)

        if slot.is_r64:
            seed_a, seed_b = slot.seed_matchup
            team_a = self._teams_by_region.get((seed_a, slot.region_index))
            team_b = self._teams_by_region.get((seed_b, slot.region_index))
            return team_a, team_b

        feeder_a, feeder_b = slot.feeder_game_ids
        return outcomes.get(feeder_a), outcomes.get(feeder_b)

    def save(self, path: Path) -> None:
        """Save trace pool to disk."""
        if not self.is_generated:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            outcome_teams=self._outcome_teams,
            baseline_probs=self._baseline_probs,
            remaining_games=np.array(self._remaining),
        )
        logger.info("Saved trace pool to %s", path)

    def load(self, path: Path) -> bool:
        """Load trace pool from disk. Returns True if successful."""
        if not path.exists():
            return False
        try:
            data = np.load(path, allow_pickle=True)
            saved_remaining = list(data["remaining_games"])
            if saved_remaining != self._remaining:
                logger.warning("Trace pool stale (games changed), regenerating")
                return False
            self._outcome_teams = data["outcome_teams"]
            self._baseline_probs = data["baseline_probs"]
            self._n_traces = self._outcome_teams.shape[0]
            self._game_id_to_col = {gid: i for i, gid in enumerate(self._remaining)}
            logger.info("Loaded %d traces from %s", self._n_traces, path)
            return True
        except Exception as e:
            logger.warning("Failed to load trace pool: %s", e)
            return False


def _rank_scores(scores: np.ndarray) -> np.ndarray:
    """Rank scores descending (1 = best). Ties get the same rank."""
    n = len(scores)
    order = np.argsort(-scores)
    ranks = np.empty(n, dtype=np.int32)
    rank = 1
    for i, idx in enumerate(order):
        if i > 0 and scores[order[i]] < scores[order[i - 1]]:
            rank = i + 1
        ranks[idx] = rank
    return ranks
