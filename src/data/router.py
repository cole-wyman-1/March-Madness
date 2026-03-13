"""FastAPI routes for bracket data — groups and entries."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.data.models import GroupInfo
from src.data.store import DataStore

logger = logging.getLogger(__name__)


class BracketPickResponse(BaseModel):
    game_id: int
    round: int
    region: str | None
    team_name: str
    is_correct: bool | None  # None if game not yet played


class EntryDetailResponse(BaseModel):
    entry_id: str
    entry_name: str
    owner_name: str
    current_score: int
    picks: list[BracketPickResponse]


class AddGroupRequest(BaseModel):
    platform: str  # "espn" only for now
    group_id: str  # ESPN group UUID


def fetch_espn_group(
    group_id: str,
    store: DataStore,
    on_state_changed: callable | None = None,
) -> GroupInfo:
    """Fetch an ESPN group and load it into the store.

    Fetches propositions, region map, group entries from ESPN,
    parses them, and stores the result. Also updates tournament state.

    Args:
        on_state_changed: Optional callback invoked after tournament state updates.
            Used to regenerate the trace pool.
    """
    from src.data.scrapers.espn.scraper import ESPNClient
    from src.data.scrapers.espn.parser import ESPNParser

    with ESPNClient() as client:
        region_map = client.fetch_region_map()
        all_props = client.fetch_all_propositions()
        group_data = client.fetch_group(group_id, use_cache=False)

        parser = ESPNParser(all_props, region_map=region_map, year=client.year)
        group_info = parser.parse_group_info(group_data)
        entries = parser.parse_entries(group_data, group_info.group_id)
        state = parser.parse_tournament_state()

        store.add_group(group_info, entries)
        store.set_tournament_state(state)
        store.save_group_registrations()

        if on_state_changed:
            on_state_changed()

        logger.info(
            "Loaded ESPN group %s (%s) — %d entries",
            group_info.group_name, group_info.group_id, len(entries),
        )
        return group_info


def create_data_router(
    store: DataStore,
    on_state_changed: callable | None = None,
) -> APIRouter:
    router = APIRouter(tags=["data"])

    @router.get("/groups", response_model=list[GroupInfo])
    def list_groups():
        return store.list_groups()

    @router.get("/groups/{group_id}")
    def get_group(group_id: str):
        group = store.get_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group

    @router.post("/groups", response_model=GroupInfo)
    def add_group(request: AddGroupRequest):
        if request.platform != "espn":
            raise HTTPException(
                status_code=400,
                detail=f"Platform '{request.platform}' not supported yet. Use 'espn'.",
            )

        existing = store.get_group(request.group_id)
        if existing:
            return existing

        try:
            return fetch_espn_group(request.group_id, store, on_state_changed)
        except Exception as e:
            logger.exception("Failed to fetch ESPN group %s", request.group_id)
            raise HTTPException(status_code=502, detail=f"Failed to fetch group: {e}")

    @router.post("/groups/{group_id}/refresh", response_model=GroupInfo)
    def refresh_group(group_id: str):
        group = store.get_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")

        try:
            return fetch_espn_group(group_id, store, on_state_changed)
        except Exception as e:
            logger.exception("Failed to refresh group %s", group_id)
            raise HTTPException(status_code=502, detail=f"Failed to refresh: {e}")

    @router.delete("/groups/{group_id}")
    def delete_group(group_id: str):
        if not store.remove_group(group_id):
            raise HTTPException(status_code=404, detail="Group not found")
        store.save_group_registrations()
        return {"status": "deleted", "group_id": group_id}

    @router.get("/entries/{entry_id}", response_model=EntryDetailResponse)
    def get_entry_detail(entry_id: str):
        entry = store.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")

        state = store.get_tournament_state()
        completed = {g.game_slot.game_id: g.winner for g in state.completed_games}

        picks = []
        score = 0
        round_points = {1: 10, 2: 20, 3: 40, 4: 80, 5: 160, 6: 320}

        for p in entry.picks:
            gid = p.game_slot.game_id
            is_correct = None
            if gid in completed:
                is_correct = p.team_name == completed[gid]
                if is_correct:
                    score += round_points.get(p.game_slot.round.value, 0)

            picks.append(BracketPickResponse(
                game_id=gid,
                round=p.game_slot.round.value,
                region=p.game_slot.region,
                team_name=p.team_name,
                is_correct=is_correct,
            ))

        picks.sort(key=lambda p: (p.round, p.game_id))

        return EntryDetailResponse(
            entry_id=entry.entry_id,
            entry_name=entry.entry_name,
            owner_name=entry.owner_name,
            current_score=score,
            picks=picks,
        )

    return router
