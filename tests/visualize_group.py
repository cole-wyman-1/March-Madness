"""Visualize a scraped ESPN group — entries, picks, scores, and standings.

Reads from the explore cache (data/cache/espn_explore/) and runs the full
pipeline: parse → score → project → rank.

Usage:
    python tests/visualize_group.py                  # uses first group found in cache
    python tests/visualize_group.py 599a65bc         # uses specific group (short ID prefix)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

EXPLORE_CACHE = PROJECT_ROOT / "data" / "cache" / "espn_explore"

# ESPN regionId -> proper name (from challenge root settings)
REGION_MAP = {1: "South", 2: "West", 3: "East", 4: "Midwest"}


def load_propositions() -> list[dict]:
    """Load all 63 propositions from explore cache."""
    all_props = []
    for period in range(1, 7):
        path = EXPLORE_CACHE / f"explore_2025_sp{period}.json"
        if not path.exists():
            print(f"Missing cache: {path}")
            continue
        data = json.loads(path.read_text())
        for p in data.get("propositions", []):
            p["_round"] = period
        all_props.extend(data.get("propositions", []))
    return all_props


def find_group_cache(prefix: str | None = None) -> Path | None:
    """Find a group cache file, optionally matching a prefix."""
    group_files = sorted(EXPLORE_CACHE.glob("explore_2025_group_*.json"))
    if not group_files:
        return None
    if prefix:
        for f in group_files:
            if prefix in f.name:
                return f
    return group_files[0]


def fix_team_region(teams, region_map):
    """Fix numeric regionId to proper name."""
    from src.data.models import Team
    fixed = []
    for t in teams:
        region = t.region
        if region.isdigit():
            region = region_map.get(int(region), region)
        fixed.append(Team(name=t.name, seed=t.seed, region=region))
    return fixed


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else None

    # Load data
    all_props = load_propositions()
    if not all_props:
        print("No propositions in cache. Run explore_espn_api.py first.")
        return

    group_path = find_group_cache(prefix)
    if not group_path:
        print("No group data in cache. Run explore_espn_api.py <group-id> first.")
        return

    group_data = json.loads(group_path.read_text())
    settings = group_data.get("groupSettings", {})
    group_name = settings.get("name", "Unknown")

    print(f"{'='*70}")
    print(f"  {group_name}")
    print(f"  {len(group_data.get('entries', []))} entries")
    print(f"{'='*70}")

    # Parse with ESPNParser
    from src.data.scrapers.espn.parser import ESPNParser
    parser = ESPNParser(all_props)

    group_info = parser.parse_group_info(group_data)
    entries = parser.parse_entries(group_data, group_info.group_id)
    state = parser.parse_tournament_state()

    # Fix regions
    state_teams = fix_team_region(state.teams, REGION_MAP)
    from src.data.models import TournamentState
    state = TournamentState(
        year=state.year,
        completed_games=state.completed_games,
        teams=state_teams,
    )

    print(f"\n  Tournament: {len(state.completed_games)}/63 games completed, "
          f"{state.games_remaining} remaining\n")

    # Score each entry
    from src.standings.scoring import score_entry

    # Build outcomes + game_rounds from tournament state
    outcomes = {g.game_slot.game_id: g.winner for g in state.completed_games}
    game_rounds = {g.game_slot.game_id: g.game_slot.round for g in state.completed_games}

    scored = []
    for e in entries:
        pts = score_entry(e.pick_by_game, outcomes, game_rounds)
        champ = e.pick_by_game.get(63, "?")
        scored.append((e, pts, champ))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Display leaderboard
    print(f"  {'Rank':<5} {'Score':<7} {'Entry':<30} {'Owner':<20} {'Champion'}")
    print(f"  {'-'*5} {'-'*7} {'-'*30} {'-'*20} {'-'*15}")
    for i, (entry, pts, champ) in enumerate(scored, 1):
        print(f"  {i:<5} {pts:<7} {entry.entry_name:<30} {entry.owner_name:<20} {champ}")

    # Run projections if tournament isn't complete
    if state.games_remaining > 0:
        print(f"\n{'='*70}")
        print(f"  Projections ({state.games_remaining} games remaining)")
        print(f"{'='*70}")

        from src.ncaa.bracket import build_bracket
        from src.ncaa.matchups import seed_win_prob
        from src.projections.engine import ProjectionEngine
        from src.standings.engine import StandingsEngine

        REGION_NAMES = ["East", "West", "South", "Midwest"]
        bracket = build_bracket(REGION_NAMES)

        seed_lookup = {t.name: t.seed for t in state.teams}
        def matchup_fn(a: str, b: str) -> float:
            sa, sb = seed_lookup.get(a), seed_lookup.get(b)
            if sa is not None and sb is not None:
                return seed_win_prob(sa, sb)
            return 0.5

        # Standings simulation
        standings_engine = StandingsEngine(bracket, matchup_fn, state, entries)
        standings = standings_engine.compute()
        standings.sort(key=lambda s: s.expected_final_score, reverse=True)

        print(f"\n  {'Rank':<5} {'Current':<9} {'Expected':<10} {'P(1st)':<8} {'P(Top3)':<9} {'Entry'}")
        print(f"  {'-'*5} {'-'*9} {'-'*10} {'-'*8} {'-'*9} {'-'*25}")
        for i, s in enumerate(standings, 1):
            p1 = s.rank_probabilities.get(1, 0) * 100
            p3 = s.top_3_prob * 100
            print(f"  {i:<5} {s.current_score:<9} {s.expected_final_score:<10.1f} "
                  f"{p1:<8.1f}% {p3:<8.1f}% {s.entry_name}")

        # Championship probabilities
        engine = ProjectionEngine(bracket, matchup_fn, state)
        engine.compute()
        adv = engine.get_advancement_probs()

        # Filter to championship round (round 6)
        champ_probs = []
        for team, rounds in adv.items():
            p = rounds.get(6, 0)
            if p > 0.005:
                seed = seed_lookup.get(team, 0)
                champ_probs.append((team, seed, p))
        champ_probs.sort(key=lambda x: x[2], reverse=True)

        if champ_probs:
            print(f"\n  Championship Probabilities (top 10):")
            print(f"  {'Team':<25} {'Seed':<6} {'P(Champ)'}")
            print(f"  {'-'*25} {'-'*6} {'-'*10}")
            for team, seed, p in champ_probs[:10]:
                bar = "█" * int(p * 50)
                print(f"  {team:<25} {seed:<6} {p*100:5.1f}% {bar}")

    print(f"\n{'='*70}")


if __name__ == "__main__":
    main()
