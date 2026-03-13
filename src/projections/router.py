"""FastAPI routes for projections — bracket probabilities and what-if simulation."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.models import (
    AdvancementEntry,
    ProjectionResult,
    SimulateRequest,
    StandingsResult,
    TournamentState,
)
from src.data.store import DataStore
from src.ncaa.bracket import build_bracket
from src.ncaa.matchups import build_matchup_fn
from src.projections.engine import ProjectionEngine
from src.standings.engine import StandingsEngine
from src.adjustments.overrides import apply_locks


REGION_NAMES = ["East", "West", "South", "Midwest"]


class ProjectionsResponse(BaseModel):
    projections: list[ProjectionResult]
    advancement: list[AdvancementEntry]
    games_remaining: int
    last_updated: str


class SimulateResponse(BaseModel):
    projections: list[ProjectionResult]
    advancement: list[AdvancementEntry]
    standings: list[StandingsResult] | None = None
    games_remaining: int


def _build_advancement(engine: ProjectionEngine, state: TournamentState) -> list[AdvancementEntry]:
    """Convert engine advancement probs to AdvancementEntry list."""
    adv = engine.get_advancement_probs()
    team_info = {t.name: t for t in state.teams}
    entries = []
    for team_name, probs in adv.items():
        t = team_info.get(team_name)
        if t is None:
            continue
        entries.append(AdvancementEntry(
            team=team_name,
            seed=t.seed,
            region=t.region,
            probabilities=probs,
        ))
    return entries


def create_projections_router(store: DataStore) -> APIRouter:
    router = APIRouter(tags=["projections"])

    @router.get("/projections", response_model=ProjectionsResponse)
    def get_projections():
        bracket = build_bracket(REGION_NAMES)
        state = store.get_tournament_state()
        matchup_fn = build_matchup_fn(state, store.ratings)

        engine = ProjectionEngine(bracket, matchup_fn, state)
        projections = engine.compute()
        advancement = _build_advancement(engine, state)

        return ProjectionsResponse(
            projections=projections,
            advancement=advancement,
            games_remaining=state.games_remaining,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    @router.post("/projections/simulate", response_model=SimulateResponse)
    def simulate(request: SimulateRequest):
        bracket = build_bracket(REGION_NAMES)
        state = store.get_tournament_state()
        matchup_fn = build_matchup_fn(state, store.ratings)

        # Apply game locks — cascades backward through bracket path
        locked_state = state
        if request.locks:
            locked_state = apply_locks(bracket, state, request.locks)

        # Build prob_overrides dict from request
        prob_overrides: dict[int, float] = {}
        for override in request.probability_overrides:
            prob_overrides[override.game_id] = override.prob_a_wins

        # Run projection engine (always uses analytical approach for per-game probs)
        engine = ProjectionEngine(bracket, matchup_fn, locked_state, prob_overrides=prob_overrides)
        projections = engine.compute()
        advancement = _build_advancement(engine, locked_state)

        # Compute standings for a group
        standings = None
        if request.group_id:
            group = store.get_group(request.group_id)
            if not group:
                raise HTTPException(status_code=404, detail="Group not found")
            entries = store.get_entries(request.group_id)
            if entries:
                # Use trace pool if available — much faster for what-if
                trace_pool = store.trace_pool
                if trace_pool is not None and trace_pool.is_generated:
                    locks_dict = {l.game_id: l.winner for l in request.locks}
                    standings = trace_pool.compute_standings(
                        entries,
                        locks=locks_dict,
                        prob_overrides=prob_overrides,
                    )
                else:
                    # Fallback to direct MC simulation
                    standings_engine = StandingsEngine(
                        bracket, matchup_fn, locked_state, entries,
                        prob_overrides=prob_overrides,
                    )
                    standings = standings_engine.compute()

                standings.sort(
                    key=lambda s: s.rank_probabilities.get(1, 0),
                    reverse=True,
                )

        return SimulateResponse(
            projections=projections,
            advancement=advancement,
            standings=standings,
            games_remaining=locked_state.games_remaining,
        )

    return router
