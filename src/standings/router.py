"""FastAPI routes for standings — simulation results."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.models import GroupInfo, StandingsResult, TournamentState
from src.data.store import DataStore
from src.ncaa.bracket import build_bracket
from src.ncaa.matchups import build_matchup_fn
from src.standings.engine import StandingsEngine


class GroupStandingsResponse(BaseModel):
    group: GroupInfo
    standings: list[StandingsResult]
    games_remaining: int
    last_updated: str


def create_standings_router(store: DataStore) -> APIRouter:
    router = APIRouter(tags=["standings"])

    @router.get("/standings/{group_id}", response_model=GroupStandingsResponse)
    def get_standings(group_id: str):
        group = store.get_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        entries = store.get_entries(group_id)
        if not entries:
            raise HTTPException(status_code=404, detail="No entries found for group")

        state = store.get_tournament_state()

        # Use trace pool if available for faster computation
        if store.trace_pool is not None and store.trace_pool.is_generated:
            standings = store.trace_pool.compute_standings(entries)
        else:
            bracket = build_bracket(["East", "West", "South", "Midwest"])
            matchup_fn = build_matchup_fn(state, store.ratings)
            engine = StandingsEngine(bracket, matchup_fn, state, entries)
            standings = engine.compute()

        standings.sort(
            key=lambda s: s.rank_probabilities.get(1, 0),
            reverse=True,
        )

        return GroupStandingsResponse(
            group=group,
            standings=standings,
            games_remaining=state.games_remaining,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    return router
