"""In-memory data store for bracket entries and groups.

Provides a central place to load, persist, and query bracket data.
Group registrations (platform + group_id) are persisted to JSON so they
survive server restarts. Entry data is re-fetched from ESPN on startup.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.data.models import BracketEntry, GroupInfo, TournamentState

GROUPS_FILE = Path("data/groups.json")


class DataStore:
    """In-memory store for bracket groups and entries."""

    def __init__(self):
        self._groups: dict[str, GroupInfo] = {}
        self._entries: dict[str, list[BracketEntry]] = {}  # group_id -> entries
        self._tournament_state: TournamentState = TournamentState(year=2025)
        self.trace_pool = None  # Optional TracePool instance
        self.ratings = None  # Optional RatingsProvider instance

    def add_group(self, group: GroupInfo, entries: list[BracketEntry]) -> None:
        """Add or replace a group and its entries."""
        self._groups[group.group_id] = group
        self._entries[group.group_id] = entries

    def remove_group(self, group_id: str) -> bool:
        """Remove a group and its entries. Returns True if found."""
        if group_id not in self._groups:
            return False
        del self._groups[group_id]
        self._entries.pop(group_id, None)
        return True

    def list_groups(self) -> list[GroupInfo]:
        """List all loaded groups."""
        return list(self._groups.values())

    def get_group(self, group_id: str) -> GroupInfo | None:
        """Get group info by ID."""
        return self._groups.get(group_id)

    def get_entries(self, group_id: str) -> list[BracketEntry]:
        """Get all entries for a group."""
        return self._entries.get(group_id, [])

    def get_entry(self, entry_id: str) -> BracketEntry | None:
        """Find a single entry by ID across all groups."""
        for entries in self._entries.values():
            for e in entries:
                if e.entry_id == entry_id:
                    return e
        return None

    def set_tournament_state(self, state: TournamentState) -> None:
        self._tournament_state = state

    def get_tournament_state(self) -> TournamentState:
        return self._tournament_state

    @property
    def total_entries(self) -> int:
        return sum(len(e) for e in self._entries.values())

    # ------------------------------------------------------------------
    # Persistence — save/load group registrations (platform + group_id)
    # ------------------------------------------------------------------

    def save_group_registrations(self) -> None:
        """Persist registered group IDs + platforms to disk."""
        registrations = [
            {"platform": g.platform, "group_id": g.group_id}
            for g in self._groups.values()
        ]
        GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        GROUPS_FILE.write_text(json.dumps(registrations, indent=2))

    @staticmethod
    def load_group_registrations() -> list[dict]:
        """Load saved group registrations from disk.

        Returns list of {"platform": str, "group_id": str} dicts.
        """
        if not GROUPS_FILE.exists():
            return []
        try:
            return json.loads(GROUPS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
