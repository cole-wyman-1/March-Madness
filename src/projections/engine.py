"""Projection engine — conditional per-game win probabilities across the bracket.

Computes two things:
1. Team advancement probabilities — P(team reaches and wins game G) for every team
   at every stage. Used by the dashboard to show bracket projections.
2. Matchup probability function — P(A beats B) for any pair. Used by the standings
   engine to simulate tournament outcomes.

The key insight: later-round probabilities are conditional. P(Duke wins their R32 game)
depends on who they face, which depends on the R64 results. We compute this by summing
over all possible opponents weighted by each opponent's advancement probability.
"""

from __future__ import annotations

from typing import Callable

from src.data.models import (
    GameResult,
    ProjectionResult,
    Round,
    TeamProb,
    TournamentState,
)
from src.ncaa.bracket import Bracket, BracketSlot


# Type alias for matchup probability function
# Takes (team_a, team_b) -> P(team_a wins)
MatchupFn = Callable[[str, str], float]


class ProjectionEngine:
    """Computes bracket-wide conditional win probabilities.

    Args:
        bracket: The 63-game bracket topology.
        matchup_fn: Function that returns P(team_a beats team_b) for any pair.
        state: Current tournament state (completed games + teams).
    """

    def __init__(
        self,
        bracket: Bracket,
        matchup_fn: MatchupFn,
        state: TournamentState,
        prob_overrides: dict[int, float] | None = None,
    ):
        self.bracket = bracket
        self.matchup_fn = matchup_fn
        self.state = state
        self._prob_overrides: dict[int, float] = prob_overrides or {}

        # team_name -> seed, built from tournament state
        self._team_seeds: dict[str, int] = {
            t.name: t.seed for t in state.teams
        }

        # Advancement probabilities: game_id -> {team_name: probability}
        # For game G, adv_probs[G][team] = P(team reaches game G)
        self._reach_probs: dict[int, dict[str, float]] = {}

        # Win probabilities: game_id -> {team_name: probability}
        # win_probs[G][team] = P(team wins game G) = P(reaches G) * P(wins | reaches G)
        self._win_probs: dict[int, dict[str, float]] = {}

        # Winners of completed games
        self._winners: dict[int, str] = {}
        for g in state.completed_games:
            self._winners[g.game_slot.game_id] = g.winner

    def compute(self) -> list[ProjectionResult]:
        """Run the full projection and return per-game results.

        Processes the bracket round by round (R64 first, then R32, etc.)
        so that each round's probabilities are informed by earlier rounds.
        """
        self._reach_probs.clear()
        self._win_probs.clear()

        # Process each round in order
        for round_val in Round:
            game_ids = self.bracket.games_in_round(round_val)
            for gid in game_ids:
                self._compute_game(gid)

        return self._build_results()

    def get_reach_probs(self, game_id: int) -> dict[str, float]:
        """Get probability of each team reaching a specific game."""
        return dict(self._reach_probs.get(game_id, {}))

    def get_win_probs(self, game_id: int) -> dict[str, float]:
        """Get probability of each team winning a specific game."""
        return dict(self._win_probs.get(game_id, {}))

    def get_advancement_probs(self) -> dict[str, dict[int, float]]:
        """Get each team's probability of winning each round.

        Returns: {team_name: {round_value: probability}}
        Useful for dashboard bracket visualization.
        """
        result: dict[str, dict[int, float]] = {}
        for gid, win_probs in self._win_probs.items():
            round_val = self.bracket.slot(gid).round.value
            for team, prob in win_probs.items():
                if prob <= 0:
                    continue
                if team not in result:
                    result[team] = {}
                # A team may appear in multiple games of the same round
                # (shouldn't happen in a valid bracket, but sum just in case)
                result[team][round_val] = result[team].get(round_val, 0) + prob
        return result

    def _compute_game(self, game_id: int) -> None:
        """Compute reach and win probabilities for a single game."""
        slot = self.bracket.slot(game_id)

        if game_id in self._winners:
            # Game is completed — winner is certain
            self._compute_completed_game(game_id, slot)
        elif slot.is_r64:
            self._compute_r64_game(game_id, slot)
        else:
            self._compute_later_round_game(game_id, slot)

    def _compute_completed_game(self, game_id: int, slot: BracketSlot) -> None:
        """Handle a completed game — winner has P=1.0."""
        winner = self._winners[game_id]

        # Find the loser from completed games
        loser = None
        for g in self.state.completed_games:
            if g.game_slot.game_id == game_id:
                loser = g.loser
                break

        reach = {}
        win = {}

        reach[winner] = 1.0
        win[winner] = 1.0

        if loser and loser != "Unknown":
            reach[loser] = 1.0
            win[loser] = 0.0

        self._reach_probs[game_id] = reach
        self._win_probs[game_id] = win

    def _compute_r64_game(self, game_id: int, slot: BracketSlot) -> None:
        """Compute probabilities for a Round of 64 game.

        Teams are known from the bracket — look up matchup probability directly.
        """
        # Find the two teams from seed matchup and region
        seed_a, seed_b = slot.seed_matchup
        team_a = self._find_team(seed_a, slot.region_index)
        team_b = self._find_team(seed_b, slot.region_index)

        if team_a is None or team_b is None:
            # Teams not yet known (bracket not seeded)
            self._reach_probs[game_id] = {}
            self._win_probs[game_id] = {}
            return

        p_a = self.matchup_fn(team_a, team_b)

        # Apply user override if present
        if game_id in self._prob_overrides:
            p_a = self._prob_overrides[game_id]

        self._reach_probs[game_id] = {team_a: 1.0, team_b: 1.0}
        self._win_probs[game_id] = {team_a: p_a, team_b: 1.0 - p_a}

    def _compute_later_round_game(self, game_id: int, slot: BracketSlot) -> None:
        """Compute probabilities for R32+ games.

        Each team's probability of winning this game is:
          P(team wins game G) = P(team reaches G) * P(team wins G | reaches G)

        Where P(team wins G | reaches G) is averaged over all possible opponents,
        weighted by their probability of reaching G.
        """
        feeder_a, feeder_b = slot.feeder_game_ids

        # Teams that could reach this game from each feeder
        winners_a = self._win_probs.get(feeder_a, {})
        winners_b = self._win_probs.get(feeder_b, {})

        reach: dict[str, float] = {}
        win: dict[str, float] = {}

        # From feeder A: P(team reaches this game) = P(team won feeder A)
        for team, p_won in winners_a.items():
            if p_won > 0:
                reach[team] = p_won

        # From feeder B
        for team, p_won in winners_b.items():
            if p_won > 0:
                reach[team] = p_won

        # Compute win probability for each team that could reach this game
        for team_x, p_reach_x in reach.items():
            if p_reach_x <= 0:
                continue

            # Team X's conditional win probability, averaged over possible opponents
            # P(X wins | X reaches) = sum over opponents Y of:
            #   P(Y reaches) * P(X beats Y) / (sum of opponent reach probs)
            p_win_given_reach = 0.0
            opponent_total = 0.0

            # Opponents come from the OTHER feeder
            if team_x in winners_a:
                opponents = winners_b
            else:
                opponents = winners_a

            for team_y, p_reach_y in opponents.items():
                if p_reach_y <= 0:
                    continue
                opponent_total += p_reach_y

                if game_id in self._prob_overrides:
                    # Override: prob_a_wins means "feeder_a side wins"
                    override_p = self._prob_overrides[game_id]
                    p_x_beats_y = override_p if team_x in winners_a else (1.0 - override_p)
                else:
                    p_x_beats_y = self.matchup_fn(team_x, team_y)

                p_win_given_reach += p_reach_y * p_x_beats_y

            if opponent_total > 0:
                p_win_given_reach /= opponent_total

            win[team_x] = p_reach_x * p_win_given_reach

        self._reach_probs[game_id] = reach
        self._win_probs[game_id] = win

    def _find_team(self, seed: int, region_index: int | None) -> str | None:
        """Find team name by seed and region index."""
        if region_index is None:
            return None

        region_name = self.bracket.region_names[region_index]
        for t in self.state.teams:
            if t.seed == seed and t.region == region_name:
                return t.name

        # Try matching by region index string (ESPN uses numeric region IDs)
        region_str = str(region_index)
        for t in self.state.teams:
            if t.seed == seed and t.region == region_str:
                return t.name

        return None

    def _build_results(self) -> list[ProjectionResult]:
        """Convert internal probabilities to ProjectionResult list."""
        results = []
        for gid in sorted(self.bracket.slots):
            slot = self.bracket.slot(gid)
            win_probs = self._win_probs.get(gid, {})
            is_completed = gid in self._winners

            # Get the top two teams by win probability (or reach probability for display)
            reach = self._reach_probs.get(gid, {})
            all_teams = set(win_probs.keys()) | set(reach.keys())

            if not all_teams:
                results.append(ProjectionResult(
                    game_id=gid,
                    round=slot.round,
                    team_a="TBD",
                    team_b="TBD",
                    prob_a_wins=0.5,
                    is_completed=is_completed,
                ))
                continue

            # Sort by reach probability to find the most likely participants
            sorted_teams = sorted(all_teams, key=lambda t: reach.get(t, 0), reverse=True)
            team_a = sorted_teams[0]
            team_b = sorted_teams[1] if len(sorted_teams) > 1 else "TBD"

            # For completed games, team_a is the winner
            if is_completed:
                winner = self._winners[gid]
                loser_candidates = [t for t in sorted_teams if t != winner]
                team_a = winner
                team_b = loser_candidates[0] if loser_candidates else "Unknown"
                prob_a = 1.0
            else:
                # prob_a_wins is the marginal probability of team_a winning this game
                total_win = sum(win_probs.values())
                prob_a = win_probs.get(team_a, 0) / total_win if total_win > 0 else 0.5

            # Build eligible_teams for unconfirmed later-round games
            eligible = None
            if not is_completed and slot.round.value > 1 and len(win_probs) > 2:
                eligible = [
                    TeamProb(team=t, prob=round(p, 4))
                    for t, p in sorted(win_probs.items(), key=lambda x: x[1], reverse=True)
                    if p > 0.01
                ]

            results.append(ProjectionResult(
                game_id=gid,
                round=slot.round,
                team_a=team_a,
                team_b=team_b,
                prob_a_wins=prob_a,
                is_completed=is_completed,
                eligible_teams=eligible,
            ))

        return results
