"""Exploratory script to validate ESPN bracket group access for arbitrary users.

This is a READ-ONLY exploration — no existing code or caches are modified.
Caches go to a separate temp directory (data/cache/espn_explore/).

Questions we're answering:
1. Can we access PRIVATE groups by ID without ESPN auth?
2. For small groups (<50), do we get all entries in one call?
3. For larger groups (50-5000), is there pagination? What params work?
4. Does the existing parser handle real private group data?
5. KNOWN ISSUE: Does the parser produce correct region names?
   (ESPN uses regionId 1-4, our models expect "East"/"West"/"South"/"Midwest")

Usage:
    python tests/explore_espn_api.py <group-id>           # test one group
    python tests/explore_espn_api.py <id1> <id2> <id3>    # test multiple groups
    python tests/explore_espn_api.py --clear-cache         # wipe explore cache and re-fetch

Find your group ID:
    Go to ESPN Tournament Challenge -> Your Group -> look at the URL:
    https://fantasy.espn.com/games/tournament-challenge-bracket-2025/group?id=YOUR-GROUP-ID
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

# Isolated cache — NOT the main app cache
EXPLORE_CACHE = Path("data/cache/espn_explore")
EXPLORE_CACHE.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://gambit-api.fantasy.espn.com/apis/v1/challenges"
YEAR = 2025


# ============================================================
# HTTP helpers
# ============================================================

def fetch(url: str, params: dict | None = None, cache_key: str | None = None) -> dict | list | None:
    """Fetch URL with optional caching. Returns None on error."""
    if cache_key:
        cache_path = EXPLORE_CACHE / f"{cache_key}.json"
        if cache_path.exists():
            print(f"  [cache hit] {cache_key}")
            return json.loads(cache_path.read_text())

    print(f"  [fetching] {url}")
    if params:
        print(f"    params: {params}")

    try:
        resp = httpx.get(url, params=params, timeout=15.0)
        print(f"    status: {resp.status_code}")

        if resp.status_code == 404:
            print("    ✗ Not found — wrong ID format, deleted group, or wrong year")
            return None
        if resp.status_code == 403:
            print("    ✗ 403 Forbidden — this group requires ESPN authentication")
            print(f"    body: {resp.text[:500]}")
            return None
        if resp.status_code == 401:
            print("    ✗ 401 Unauthorized — ESPN requires login for this resource")
            print(f"    body: {resp.text[:500]}")
            return None
        if resp.status_code != 200:
            print(f"    ✗ Unexpected status {resp.status_code}")
            print(f"    body: {resp.text[:500]}")
            return None

        data = resp.json()
        if cache_key:
            cache_path = EXPLORE_CACHE / f"{cache_key}.json"
            cache_path.write_text(json.dumps(data, indent=2))
        return data

    except httpx.ConnectError:
        print("    ✗ Connection failed — check internet connection")
        return None
    except httpx.TimeoutException:
        print("    ✗ Request timed out (15s)")
        return None
    except httpx.HTTPError as e:
        print(f"    ✗ HTTP error: {e}")
        return None


# ============================================================
# Test 1: Fetch propositions (63 games) + region mapping
# ============================================================

def fetch_propositions() -> tuple[list[dict], dict[int, str]] | tuple[None, None]:
    """Fetch all 63 game propositions and the region name mapping.

    Returns (all_props, region_map) where region_map is {regionId: "East", ...}
    """
    print(f"\n{'='*60}")
    print(f"TEST 1: Fetch 2025 tournament data")
    print(f"{'='*60}")

    slug = f"tournament-challenge-bracket-{YEAR}"
    url = f"{BASE_URL}/{slug}"

    # First fetch root challenge (no scoring period) to get region name mapping
    root = fetch(url, cache_key=f"explore_{YEAR}_root")
    region_map: dict[int, str] = {}
    if root:
        settings = root.get("settings", {})
        raw_regions = settings.get("regionNames", {})
        # ESPN returns {"1": "SOUTH", "2": "WEST", "3": "EAST", "4": "MIDWEST"}
        for k, v in raw_regions.items():
            region_map[int(k)] = v.title()  # "SOUTH" -> "South"
        print(f"  Region mapping: {region_map}")

        # Check tournament status
        state = root.get("state", "?")
        scoring_status = root.get("scoringStatus", "?")
        print(f"  Tournament state: {state}")
        print(f"  Scoring status: {scoring_status}")
    else:
        print("  ✗ Could not fetch challenge root — cannot proceed")
        return None, None

    # Now fetch all 6 rounds
    all_props = []
    round_names = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "F4", 6: "NCG"}

    for period in range(1, 7):
        data = fetch(url, params={"scoringPeriodId": period},
                     cache_key=f"explore_{YEAR}_sp{period}")
        if data is None:
            print(f"  {round_names[period]}: ✗ FAILED")
            continue

        props = data.get("propositions", [])
        statuses: dict[str, int] = {}
        for p in props:
            s = p.get("status", "?")
            statuses[s] = statuses.get(s, 0) + 1
            p["_round"] = period

        all_props.extend(props)
        print(f"  {round_names[period]}: {len(props)} games — {statuses}")

    print(f"\n  Total propositions: {len(all_props)}")
    if len(all_props) != 63:
        print(f"  ⚠ Expected 63, got {len(all_props)} — API may have changed")

    # Verify region mapping covers all regionIds in the data
    r1_region_ids = set()
    for p in all_props:
        if p.get("_round") == 1:
            for o in p.get("possibleOutcomes", []):
                r1_region_ids.add(o.get("regionId"))
    unmapped = r1_region_ids - set(region_map.keys())
    if unmapped:
        print(f"  ⚠ Unmapped regionIds: {unmapped}")
    else:
        print(f"  ✓ All regionIds ({sorted(r1_region_ids)}) have names")

    return all_props, region_map


# ============================================================
# Test 2: Fetch a group by ID
# ============================================================

def test_group(group_id: str, label: str = "") -> dict | None:
    """Fetch a group and inspect its structure."""
    display = label or group_id
    print(f"\n{'='*60}")
    print(f"TEST 2: Fetch group")
    print(f"  Label: {display}")
    print(f"  ID:    {group_id}")
    print(f"{'='*60}")

    slug = f"tournament-challenge-bracket-{YEAR}"
    url = f"{BASE_URL}/{slug}/groups/{group_id}"
    short_id = group_id[:8]

    data = fetch(url, cache_key=f"explore_{YEAR}_group_{short_id}")
    if data is None:
        return None

    # Basic info
    settings = data.get("groupSettings", {})
    size = data.get("size", "?")
    name = settings.get("name", "?")
    is_public = settings.get("public", "?")
    is_large = data.get("largeGroup", False)

    print(f"\n  ✓ Group accessible!")
    print(f"  Name:        {name}")
    print(f"  Total size:  {size} entries")
    print(f"  Public:      {is_public}")
    print(f"  Large group: {is_large}")

    # Entries returned in this response
    entries = data.get("entries", [])
    print(f"  Entries in response: {len(entries)}")

    if isinstance(size, int) and len(entries) < size:
        print(f"  ⚠ Only got {len(entries)} of {size} — PAGINATION NEEDED")
        if size <= 500:
            print(f"    This group is small enough to paginate (<500)")
        elif size <= 5000:
            print(f"    Medium group — pagination feasible but may need multiple calls")
        else:
            print(f"    Very large group ({size:,}) — may need leaderboard API instead")
    elif isinstance(size, int) and len(entries) == size:
        print(f"  ✓ Got ALL {size} entries in one call — no pagination needed")

    # Response structure
    print(f"\n  Response keys: {sorted(data.keys())}")

    # Entry details
    if entries:
        print(f"\n  --- Entries ---")
        for i, e in enumerate(entries[:5]):
            member = e.get("member", {})
            picks = e.get("picks", [])
            ename = e.get("name", "?")
            owner = member.get("displayName", "?")
            print(f"    [{i+1}] \"{ename}\" by {owner} — {len(picks)} picks")

        if len(entries) > 5:
            print(f"    ... and {len(entries) - 5} more")

        # Validate pick structure
        e = entries[0]
        picks = e.get("picks", [])
        print(f"\n  --- Pick Structure (first entry) ---")
        print(f"    Entry keys: {sorted(e.keys())}")
        print(f"    Pick count: {len(picks)}")
        if picks:
            p = picks[0]
            print(f"    Pick keys: {sorted(p.keys())}")
            print(f"    propositionId present: {'propositionId' in p}")
            outcomes = p.get("outcomesPicked", [])
            print(f"    outcomesPicked count: {len(outcomes)}")
            if outcomes:
                print(f"    outcomesPicked[0] keys: {sorted(outcomes[0].keys())}")

        # Check for incomplete brackets (fewer than 63 picks)
        pick_counts = [len(e.get("picks", [])) for e in entries]
        incomplete = [c for c in pick_counts if c < 63]
        if incomplete:
            print(f"\n  ⚠ {len(incomplete)} entries have < 63 picks (min={min(incomplete)})")
        else:
            print(f"\n  ✓ All {len(entries)} entries have 63 picks")

    return data


# ============================================================
# Test 3: Pagination (only runs if group has more entries than returned)
# ============================================================

def test_pagination(group_id: str, total_size: int, first_page_entries: list[dict]):
    """Try various pagination strategies to get entries beyond the first 50."""
    print(f"\n{'='*60}")
    print(f"TEST 3: Pagination — need {total_size} entries, got {len(first_page_entries)}")
    print(f"{'='*60}")

    slug = f"tournament-challenge-bracket-{YEAR}"
    base_url = f"{BASE_URL}/{slug}/groups/{group_id}"

    # Collect first-page entry IDs to verify we get different entries
    first_page_ids = {e.get("id", e.get("name", "")) for e in first_page_entries}

    strategies = [
        ("offset + limit", {"offset": 50, "limit": 50}),
        ("page=2", {"page": 2}),
        ("page + pageSize", {"page": 2, "pageSize": 50}),
        ("start + count", {"start": 50, "count": 50}),
        ("startIndex", {"startIndex": 50}),
        ("entryOffset", {"entryOffset": 50}),
    ]

    for name, params in strategies:
        print(f"\n  Strategy: {name}")
        print(f"    Params: {params}")
        # Don't cache pagination attempts — they're exploratory
        data = fetch(base_url, params=params)
        if data and isinstance(data, dict):
            entries = data.get("entries", [])
            print(f"    Entries returned: {len(entries)}")
            if entries:
                page2_ids = {e.get("id", e.get("name", "")) for e in entries}
                overlap = first_page_ids & page2_ids
                new_entries = page2_ids - first_page_ids
                print(f"    Overlap with page 1: {len(overlap)}")
                print(f"    New entries: {len(new_entries)}")
                if new_entries:
                    print(f"    ✓ PAGINATION WORKS with {name}!")
                    first_new = entries[0]
                    print(f"    First new entry: \"{first_new.get('name', '?')}\"")
                    return name, params
                else:
                    print(f"    Same entries as page 1 — this strategy doesn't paginate")

    print(f"\n  ✗ No pagination strategy worked")
    print(f"    ESPN may cap group responses at 50 entries")
    print(f"    For groups >50, we may need to use the leaderboard API or require ESPN auth")
    return None, None


# ============================================================
# Test 4: Parser integration
# ============================================================

def run_parser(all_props: list[dict], group_data: dict, region_map: dict[int, str]):
    """Test the existing parser against real data and check for known issues."""
    print(f"\n{'='*60}")
    print(f"TEST 4: Parser integration")
    print(f"{'='*60}")

    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    try:
        from src.data.scrapers.espn.parser import ESPNParser

        parser = ESPNParser(all_props)
        print(f"  ✓ Parser initialized — {parser.game_count} games")

        # ---- Teams ----
        teams = parser.get_teams()
        print(f"  Teams found: {len(teams)}")
        if len(teams) != 64:
            print(f"  ⚠ Expected 64 teams, got {len(teams)}")

        # Check region values — this is the KNOWN ISSUE
        by_region: dict[str, list] = {}
        for t in teams:
            by_region.setdefault(t.region, []).append(t)

        print(f"\n  --- Region Check (KNOWN ISSUE) ---")
        print(f"  Parser produces these region values: {sorted(by_region.keys())}")
        print(f"  Our bracket expects: East, West, South, Midwest")
        print(f"  ESPN region mapping: {region_map}")

        regions_ok = all(
            r in ("East", "West", "South", "Midwest")
            for r in by_region.keys()
        )
        if regions_ok:
            print(f"  ✓ Region names are correct!")
        else:
            print(f"  ✗ Region names are WRONG — parser outputs numeric IDs")
            print(f"    Need to update parser to use region_map: regionId -> name")
            print(f"    Current values: {sorted(by_region.keys())}")
            print(f"    Required mapping: {region_map}")

        for region, ts in sorted(by_region.items()):
            seeds = sorted(t.seed for t in ts)
            expected_name = region_map.get(int(region), "?") if region.isdigit() else region
            print(f"    Region '{region}' ({expected_name}): {len(ts)} teams, seeds {seeds}")

        # ---- Group Info ----
        group_info = parser.parse_group_info(group_data)
        print(f"\n  --- Group ---")
        print(f"  Name: {group_info.group_name}")
        print(f"  Platform: {group_info.platform}")
        print(f"  Entry count: {group_info.entry_count}")
        print(f"  Scoring: {group_info.scoring_system}")

        # ---- Entries ----
        entries = parser.parse_entries(group_data, group_info.group_id)
        print(f"\n  --- Entries ---")
        print(f"  Parsed: {len(entries)}")
        raw_count = len(group_data.get("entries", []))
        if len(entries) < raw_count:
            print(f"  ⚠ Parser dropped {raw_count - len(entries)} entries (missing picks?)")

        if entries:
            pick_counts = [len(e.picks) for e in entries]
            print(f"  Pick counts: min={min(pick_counts)} max={max(pick_counts)} avg={sum(pick_counts)/len(pick_counts):.0f}")

            # Show entries with champion picks
            print(f"\n  Sample entries (with champion pick):")
            for e in entries[:5]:
                champ = e.pick_by_game.get(63, "?")
                print(f"    \"{e.entry_name}\" by {e.owner_name} — {len(e.picks)} picks, champion: {champ}")

            # Check for entry_id uniqueness
            ids = [e.entry_id for e in entries]
            if len(ids) != len(set(ids)):
                print(f"  ⚠ Duplicate entry IDs detected!")
            else:
                print(f"  ✓ All entry IDs unique")

        # ---- Tournament State ----
        state = parser.parse_tournament_state()
        print(f"\n  --- Tournament State ---")
        print(f"  Year: {state.year}")
        print(f"  Completed: {len(state.completed_games)} / 63")
        print(f"  Remaining: {state.games_remaining}")

        if state.completed_games:
            # Count by round
            by_round: dict[int, int] = {}
            for g in state.completed_games:
                r = g.game_slot.round.value
                by_round[r] = by_round.get(r, 0) + 1
            round_labels = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "F4", 6: "NCG"}
            for r in sorted(by_round):
                print(f"    {round_labels.get(r, f'R{r}')}: {by_round[r]} completed")

            # Show last completed game
            last = state.completed_games[-1]
            score = f" ({last.winner_score}-{last.loser_score})" if last.winner_score else ""
            print(f"  Last completed: game {last.game_slot.game_id} — {last.winner} beat {last.loser}{score}")

        # ---- Score Validation (if tournament complete) ----
        if entries and state.completed_games:
            print(f"\n  --- Scoring Sanity Check ---")
            from src.standings.scoring import score_entry
            try:
                for e in entries[:3]:
                    pts = score_entry(e, state)
                    print(f"    \"{e.entry_name}\": {pts} points")
                print(f"  ✓ Scoring works")
            except Exception as ex:
                print(f"  ⚠ Scoring failed: {ex}")
                print(f"    (May be due to region mismatch issue)")

        print(f"\n  {'✓' if regions_ok else '⚠'} Parser integration {'PASSED' if regions_ok else 'PASSED with region issue'}")

    except Exception as e:
        print(f"\n  ✗ PARSER ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 60)
    print("ESPN Bracket API Exploration (2025 tournament)")
    print("=" * 60)
    print(f"Cache: {EXPLORE_CACHE.absolute()}")
    print("This makes NO changes to existing app code or caches.")

    # Handle --clear-cache
    if "--clear-cache" in sys.argv:
        import shutil
        if EXPLORE_CACHE.exists():
            shutil.rmtree(EXPLORE_CACHE)
            EXPLORE_CACHE.mkdir(parents=True, exist_ok=True)
            print("\nCache cleared.")
        sys.argv = [a for a in sys.argv if a != "--clear-cache"]

    # Get group IDs from CLI args
    group_ids = [a for a in sys.argv[1:] if not a.startswith("-")]

    if not group_ids:
        print("""
Usage:
    python tests/explore_espn_api.py <group-id> [<group-id> ...]

Find your group ID:
    1. Go to ESPN Tournament Challenge
    2. Click on your group
    3. Look at the URL — the ID is after ?id=
       Example: ...tournament-challenge-bracket-2025/group?id=abc12345-def6-7890-...

Options:
    --clear-cache    Wipe the explore cache and re-fetch from ESPN

What this tests:
    1. Can we access your group without ESPN login? (public API)
    2. Do we get all entries? (pagination check)
    3. Does our parser correctly handle the data?
    4. Known issue: region name mapping (numeric ID vs "East"/"West"/...)
""")
        return

    # Test 1: Fetch propositions + region map
    result = fetch_propositions()
    if result[0] is None:
        print("\nCannot proceed without proposition data. Exiting.")
        return
    all_props, region_map = result

    # Test 2-4: For each group
    for i, gid in enumerate(group_ids):
        if i > 0:
            print(f"\n\n{'#'*60}")
            print(f"# GROUP {i+1} of {len(group_ids)}")
            print(f"{'#'*60}")

        # Test 2: Fetch group
        group_data = test_group(gid)
        if group_data is None:
            continue

        # Test 3: Pagination (if needed)
        size = group_data.get("size", 0)
        entries = group_data.get("entries", [])
        if isinstance(size, int) and len(entries) < size:
            test_pagination(gid, size, entries)

        # Test 4: Parser
        run_parser(all_props, group_data, region_map)

    # Summary
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Groups tested: {len(group_ids)}")
    print(f"Cached data:   {EXPLORE_CACHE.absolute()}")
    print(f"\nTo re-run fresh: python tests/explore_espn_api.py --clear-cache {' '.join(group_ids)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
