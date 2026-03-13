"""ESPN Tournament Challenge API client.

Uses ESPN's public Gambit API to fetch bracket challenge data.
No authentication required.

API endpoints:
  Challenge root (per scoring period):
    GET /apis/v1/challenges/tournament-challenge-bracket-{year}?scoringPeriodId={1-6}
    -> propositions for that round with outcome IDs mapping to teams

  Group entries:
    GET /apis/v1/challenges/tournament-challenge-bracket-{year}/groups/{groupId}
    -> entries with 63 picks (propositionId + outcomeId)

  Groups list:
    GET /apis/v1/challenges/tournament-challenge-bracket-{year}/groups
    -> public/featured groups

Key discovery: The root endpoint without scoringPeriodId returns only 1 proposition
(the championship). Adding ?scoringPeriodId=1 returns 32 R64 propositions, etc.
Each proposition has its own outcome IDs that match the pick outcomeIds.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://gambit-api.fantasy.espn.com/apis/v1/challenges"

CACHE_DIR = Path("data/cache/espn")


def _current_tournament_year() -> int:
    """Detect the current tournament year. March Madness spans March-April."""
    today = date.today()
    return today.year


class ESPNClient:
    """Fetches bracket data from ESPN's Tournament Challenge API."""

    def __init__(self, year: int | None = None):
        self.year = year or _current_tournament_year()
        self.challenge_slug = f"tournament-challenge-bracket-{self.year}"
        self.base = f"{BASE_URL}/{self.challenge_slug}"
        self._client = httpx.Client(timeout=30.0)
        self._region_map: dict[int, str] | None = None

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _get(self, url: str, params: dict | None = None) -> Any:
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, name: str) -> Path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"{self.challenge_slug}_{name}.json"

    def _load_cache(self, name: str) -> Any | None:
        path = self._cache_path(name)
        if path.exists():
            return json.loads(path.read_text())
        return None

    def _save_cache(self, name: str, data: Any) -> None:
        path = self._cache_path(name)
        path.write_text(json.dumps(data, indent=2))

    # ------------------------------------------------------------------
    # Challenge data — propositions per round
    # ------------------------------------------------------------------

    def fetch_challenge(self, scoring_period_id: int | None = None,
                        use_cache: bool = True) -> dict:
        """Fetch challenge data, optionally for a specific scoring period.

        Without scoring_period_id: returns root challenge with 1 prop (championship).
        With scoring_period_id=1: returns 32 Round of 64 propositions.
        With scoring_period_id=2: returns 16 Round of 32 propositions.
        etc.
        """
        cache_name = f"challenge_sp{scoring_period_id or 'root'}"

        if use_cache:
            cached = self._load_cache(cache_name)
            if cached:
                return cached

        params = {}
        if scoring_period_id is not None:
            params["scoringPeriodId"] = scoring_period_id

        data = self._get(self.base, params=params)
        self._save_cache(cache_name, data)
        return data

    def fetch_region_map(self, use_cache: bool = True) -> dict[int, str]:
        """Extract region name mapping from challenge root settings.

        ESPN stores region names in settings.regionNames as e.g.
        {"1": "SOUTH", "2": "WEST", "3": "EAST", "4": "MIDWEST"}.

        Returns:
            Dict mapping regionId (int) to title-cased region name.
        """
        if self._region_map is not None:
            return self._region_map

        root = self.fetch_challenge(use_cache=use_cache)
        raw = root.get("settings", {}).get("regionNames", {})
        self._region_map = {
            int(k): v.title() for k, v in raw.items()
        }
        return self._region_map

    def fetch_all_propositions(self, use_cache: bool = True) -> list[dict]:
        """Fetch all 63 game propositions across all 6 rounds.

        Returns propositions sorted by round then game order.
        Each proposition includes possibleOutcomes with team names
        and outcome IDs that match the pick outcomeIds in entries.
        """
        cache_name = "all_propositions"
        if use_cache:
            cached = self._load_cache(cache_name)
            if cached:
                return cached

        all_props = []
        for period_id in range(1, 7):
            data = self.fetch_challenge(scoring_period_id=period_id,
                                        use_cache=use_cache)
            props = data.get("propositions", [])
            # Tag each proposition with its round number
            for p in props:
                p["_round"] = period_id
            all_props.extend(props)

        self._save_cache(cache_name, all_props)
        return all_props

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def fetch_featured_groups(self, use_cache: bool = True) -> list[dict]:
        """Fetch the list of featured/public groups."""
        cache_name = "groups"
        if use_cache:
            cached = self._load_cache(cache_name)
            if cached:
                return cached

        data = self._get(f"{self.base}/groups")
        self._save_cache(cache_name, data)
        return data

    def fetch_group(self, group_id: str, use_cache: bool = True) -> dict:
        """Fetch all entries for a specific group.

        Args:
            group_id: UUID string for the group.

        Returns:
            Dict with group info and entries array (up to 50 entries).
        """
        cache_name = f"group_{group_id[:8]}"
        if use_cache:
            cached = self._load_cache(cache_name)
            if cached:
                return cached

        data = self._get(f"{self.base}/groups/{group_id}")
        self._save_cache(cache_name, data)
        return data


def _print_summary(client: ESPNClient):
    """Quick diagnostic: print challenge structure."""
    all_props = client.fetch_all_propositions()
    print(f"Challenge: {client.challenge_slug}")
    print(f"Total propositions (games): {len(all_props)}")

    # Count by round
    from collections import Counter
    by_round = Counter(p["_round"] for p in all_props)
    round_names = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "F4", 6: "NCG"}
    for r in sorted(by_round):
        print(f"  {round_names.get(r, f'R{r}')}: {by_round[r]} games")

    # Show a sample R1 game
    r1 = [p for p in all_props if p["_round"] == 1]
    if r1:
        p = r1[0]
        outcomes = p.get("possibleOutcomes", [])
        print(f"\nSample R64 game: {p.get('name', '?')}")
        for o in outcomes:
            print(f"  {o.get('name', '?')} (seed {o.get('regionSeed', '?')}) "
                  f"id={o['id'][:12]}...")


if __name__ == "__main__":
    with ESPNClient() as client:
        _print_summary(client)
