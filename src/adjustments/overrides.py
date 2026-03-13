"""Override logic for what-if scenarios — game locks and probability adjustments.

Game locks cascade backward: locking Duke to win the Elite 8 automatically
locks Duke in S16, R32, and R64. This is implemented by adding synthetic
GameResult entries to the TournamentState.
"""

from __future__ import annotations

from src.data.models import (
    GameResult,
    GameSlot,
    OverridePayload,
    TournamentState,
)
from src.ncaa.bracket import Bracket, R64_SEED_MATCHUPS


def find_team_r64_game(bracket: Bracket, state: TournamentState, team_name: str) -> int | None:
    """Find which R64 game_id a team starts in based on seed+region.

    Returns the game_id (1-32) or None if team not found.
    """
    # Find team's seed and region
    team = None
    for t in state.teams:
        if t.name == team_name:
            team = t
            break
    if team is None:
        return None

    # Find region index
    region_index = None
    for i, name in enumerate(bracket.region_names):
        if name == team.region:
            region_index = i
            break
    if region_index is None:
        return None

    # Find which R64 game has this seed
    for game_offset, (seed_a, seed_b) in enumerate(R64_SEED_MATCHUPS):
        if team.seed in (seed_a, seed_b):
            game_id = region_index * 8 + 1 + game_offset
            return game_id

    return None


def apply_locks(
    bracket: Bracket,
    state: TournamentState,
    locks: list[OverridePayload.GameLock],
) -> TournamentState:
    """Return a new TournamentState with locked games added as completed.

    For each lock, traces the team's bracket path backward from the locked
    game to their R64 game, adding synthetic GameResult entries for every
    game on the path that isn't already completed.
    """
    if not locks:
        return state

    new_completed = list(state.completed_games)
    completed_ids = {g.game_slot.game_id for g in new_completed}

    for lock in locks:
        r64_game = find_team_r64_game(bracket, state, lock.winner)
        if r64_game is None:
            continue

        # path_to_championship returns [r64, r32, s16, e8, f4, ncg]
        path = bracket.path_to_championship(r64_game)

        for gid in path:
            if gid > lock.game_id:
                break
            if gid in completed_ids:
                continue

            slot = bracket.slot(gid)
            new_completed.append(GameResult(
                game_slot=GameSlot(
                    game_id=gid,
                    round=slot.round,
                    region=bracket.region_names[slot.region_index] if slot.region_index is not None else None,
                ),
                winner=lock.winner,
                loser="LOCKED",
            ))
            completed_ids.add(gid)

    return TournamentState(
        year=state.year,
        completed_games=new_completed,
        teams=state.teams,
    )
