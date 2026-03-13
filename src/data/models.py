"""Shared Pydantic models for the March Madness Bracket Analyzer.

These models define the contracts between all agents. Any changes here
must be coordinated through the data-orchestrator agent.
"""

from __future__ import annotations

from enum import IntEnum
from pydantic import BaseModel, Field


class Round(IntEnum):
    """Tournament round (1-6)."""
    ROUND_OF_64 = 1
    ROUND_OF_32 = 2
    SWEET_16 = 3
    ELITE_8 = 4
    FINAL_4 = 5
    CHAMPIONSHIP = 6


class Platform(str):
    """Bracket platform identifier."""
    ESPN = "espn"
    CBS = "cbs"
    YAHOO = "yahoo"


class Team(BaseModel):
    """A tournament team."""
    name: str
    seed: int
    region: str  # e.g. "East", "West", "South", "Midwest"


class GameSlot(BaseModel):
    """Identifies a specific game in the bracket.

    Games are numbered 1-63:
      Round 1 (64): games 1-32
      Round 2 (32): games 33-48
      Sweet 16:     games 49-56
      Elite 8:      games 57-60
      Final 4:      games 61-62
      Championship: game 63
    """
    game_id: int = Field(ge=1, le=63)
    round: Round
    region: str | None = None  # None for Final Four / Championship

    @property
    def round_name(self) -> str:
        return self.round.name.replace("_", " ").title()


class Pick(BaseModel):
    """A single game pick within a bracket entry."""
    game_slot: GameSlot
    team_name: str  # team picked to win this game


class BracketEntry(BaseModel):
    """A single user's bracket submission.

    Contains all 63 picks (one per game in the tournament).
    """
    entry_id: str  # unique identifier (platform-specific)
    entry_name: str  # display name (e.g. "Chad's Bracket")
    owner_name: str  # user who submitted the entry
    platform: str  # "espn", "cbs", "yahoo"
    group_id: str  # which bracket group/pool this belongs to
    picks: list[Pick]  # all 63 picks
    tiebreaker: int | None = None  # predicted championship total score

    @property
    def pick_by_game(self) -> dict[int, str]:
        """Map game_id -> team_name for quick lookup."""
        return {p.game_slot.game_id: p.team_name for p in self.picks}


class GroupInfo(BaseModel):
    """Metadata about a bracket group/pool."""
    group_id: str
    group_name: str
    platform: str  # "espn", "cbs", "yahoo"
    entry_count: int
    scoring_system: str = "espn_standard"  # for future configurable scoring


class GameResult(BaseModel):
    """The actual result of a completed game."""
    game_slot: GameSlot
    winner: str  # team name
    loser: str  # team name
    winner_score: int | None = None
    loser_score: int | None = None


class TournamentState(BaseModel):
    """Current state of the tournament — completed games and remaining matchups."""
    year: int
    completed_games: list[GameResult] = Field(default_factory=list)
    teams: list[Team] = Field(default_factory=list)

    @property
    def games_remaining(self) -> int:
        return 63 - len(self.completed_games)

    @property
    def completed_game_ids(self) -> set[int]:
        return {g.game_slot.game_id for g in self.completed_games}

    def winner_of(self, game_id: int) -> str | None:
        """Get the winner of a completed game, or None if not yet played."""
        for g in self.completed_games:
            if g.game_slot.game_id == game_id:
                return g.winner
        return None


class EntryScore(BaseModel):
    """Current score for a bracket entry based on completed games."""
    entry_id: str
    current_score: int  # points earned so far
    correct_picks: int  # number of correct picks
    total_decided: int  # number of games that have been played
    max_possible: int  # maximum score still achievable


class MatchupProbability(BaseModel):
    """Win probability for a specific matchup (from ncaa-data)."""
    team_a: str
    team_b: str
    prob_a_wins: float = Field(ge=0.0, le=1.0)

    @property
    def prob_b_wins(self) -> float:
        return 1.0 - self.prob_a_wins


class TeamProb(BaseModel):
    """A team and their probability of winning a specific game."""
    team: str
    prob: float


class ProjectionResult(BaseModel):
    """Per-game win probability for a bracket game (from projection-engine).

    For completed games, the winner has prob=1.0.
    For future games, prob is conditional on which teams advance.
    """
    game_id: int = Field(ge=1, le=63)
    round: Round
    team_a: str  # higher seed or first team
    team_b: str  # lower seed or second team
    prob_a_wins: float = Field(ge=0.0, le=1.0)
    is_completed: bool = False
    eligible_teams: list[TeamProb] | None = None  # all teams that could win this game (for unconfirmed matchups)

    @property
    def prob_b_wins(self) -> float:
        return 1.0 - self.prob_a_wins


class StandingsResult(BaseModel):
    """Finish probability distribution for a single entry in a group."""
    entry_id: str
    entry_name: str
    current_score: int
    expected_final_score: float
    rank_probabilities: dict[int, float]  # rank -> probability (e.g. {1: 0.42, 2: 0.31, ...})
    top_3_prob: float
    top_5_prob: float


class OverridePayload(BaseModel):
    """User-driven game lock-ins for what-if scenarios."""

    class GameLock(BaseModel):
        game_id: int = Field(ge=1, le=63)
        winner: str  # team name forced to win

    locks: list[GameLock]


class ProbabilityOverride(BaseModel):
    """User adjustment to a single game's win probability."""
    game_id: int = Field(ge=1, le=63)
    prob_a_wins: float = Field(ge=0.0, le=1.0)


class SimulateRequest(BaseModel):
    """Request payload for the simulate endpoint."""
    locks: list[OverridePayload.GameLock] = Field(default_factory=list)
    probability_overrides: list[ProbabilityOverride] = Field(default_factory=list)
    group_id: str | None = None  # if provided, also recompute standings


class AdvancementEntry(BaseModel):
    """Per-team advancement probabilities across all rounds."""
    team: str
    seed: int
    region: str
    probabilities: dict[int, float]  # round_value -> P(advances past that round)
