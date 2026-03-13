"""Mock data for development — loads fake bracket groups and entries."""

from __future__ import annotations

import random

from src.data.models import (
    BracketEntry,
    GameSlot,
    GroupInfo,
    Pick,
    Round,
    Team,
    TournamentState,
)
from src.data.store import DataStore
from src.ncaa.bracket import build_bracket, R64_SEED_MATCHUPS

# Realistic team names by region and seed
MOCK_TEAMS = {
    "East": {
        1: "Duke", 2: "Alabama", 3: "Wisconsin", 4: "Arizona",
        5: "Oregon", 6: "BYU", 7: "Clemson", 8: "Utah",
        9: "TCU", 10: "Arkansas", 11: "Drake", 12: "UC Irvine",
        13: "Vermont", 14: "Colgate", 15: "Montana St", 16: "Norfolk St",
    },
    "West": {
        1: "Houston", 2: "Tennessee", 3: "Purdue", 4: "Kansas",
        5: "Marquette", 6: "Illinois", 7: "Saint Mary's", 8: "Florida Atlantic",
        9: "Penn State", 10: "Boise St", 11: "New Mexico", 12: "Grand Canyon",
        13: "Iona", 14: "UC Santa Barbara", 15: "Princeton", 16: "Fairleigh Dickinson",
    },
    "South": {
        1: "UConn", 2: "Auburn", 3: "Baylor", 4: "Virginia",
        5: "San Diego St", 6: "Creighton", 7: "Missouri", 8: "Maryland",
        9: "West Virginia", 10: "Utah State", 11: "NC State", 12: "Oral Roberts",
        13: "Kent State", 14: "UCSB", 15: "Kennesaw St", 16: "Texas Southern",
    },
    "Midwest": {
        1: "North Carolina", 2: "UCLA", 3: "Gonzaga", 4: "Indiana",
        5: "Miami", 6: "Kentucky", 7: "Michigan St", 8: "Memphis",
        9: "FAU", 10: "Penn", 11: "Pittsburgh", 12: "VCU",
        13: "Furman", 14: "Morehead St", 15: "Robert Morris", 16: "SE Missouri St",
    },
}

BRACKET = build_bracket(["East", "West", "South", "Midwest"])

# First names for generating owner names
FIRST_NAMES = [
    "Cole", "Jake", "Ryan", "Mike", "Chris", "Matt", "Tom", "Nick",
    "Dan", "Alex", "Sam", "Ben", "Josh", "Tyler", "Sean", "Kevin",
    "Dave", "Eric", "Brian", "Jason", "Kyle", "Jeff", "Mark", "Steve",
]

BRACKET_SUFFIXES = [
    "'s Bracket", " Madness", "'s Picks", " Chalk", " Upsets",
    " Special", " Money", " Sleeper", "", "'s Lock",
]


def _all_teams() -> list[Team]:
    teams = []
    for region, seeds in MOCK_TEAMS.items():
        for seed, name in seeds.items():
            teams.append(Team(name=name, seed=seed, region=region))
    return teams


def _team_name(seed: int, region: str) -> str:
    return MOCK_TEAMS[region][seed]


def _simulate_bracket(chalk_bias: float = 0.6) -> dict[int, str]:
    """Simulate a full bracket pick with some randomness.

    chalk_bias: probability of picking the higher seed (0.5 = random, 1.0 = all chalk).
    """
    rng = random.Random()
    picks: dict[int, str] = {}

    # R64
    for region_idx, region in enumerate(["East", "West", "South", "Midwest"]):
        base = region_idx * 8 + 1
        for i in range(8):
            gid = base + i
            high_seed, low_seed = R64_SEED_MATCHUPS[i]
            high_team = _team_name(high_seed, region)
            low_team = _team_name(low_seed, region)
            # Higher seeds more likely to be picked, scaled by seed gap
            gap = low_seed - high_seed
            p_high = chalk_bias + (1 - chalk_bias) * (gap / 15) * 0.5
            picks[gid] = high_team if rng.random() < p_high else low_team

    # Later rounds: pick from the winners of feeder games
    for round_val in [Round.ROUND_OF_32, Round.SWEET_16, Round.ELITE_8,
                      Round.FINAL_4, Round.CHAMPIONSHIP]:
        for gid in BRACKET.games_in_round(round_val):
            slot = BRACKET.slot(gid)
            feeder_a, feeder_b = slot.feeder_game_ids
            team_a = picks[feeder_a]
            team_b = picks[feeder_b]

            # Find seeds to determine chalk bias
            seed_a = _find_seed(team_a)
            seed_b = _find_seed(team_b)

            if seed_a < seed_b:
                picks[gid] = team_a if rng.random() < chalk_bias else team_b
            elif seed_b < seed_a:
                picks[gid] = team_b if rng.random() < chalk_bias else team_a
            else:
                picks[gid] = team_a if rng.random() < 0.5 else team_b

    return picks


def _find_seed(team_name: str) -> int:
    for region, seeds in MOCK_TEAMS.items():
        for seed, name in seeds.items():
            if name == team_name:
                return seed
    return 8


def _make_entry(entry_id: str, name: str, owner: str, group_id: str,
                chalk_bias: float) -> BracketEntry:
    picks_map = _simulate_bracket(chalk_bias)
    picks = []
    for gid, team in picks_map.items():
        slot = BRACKET.slot(gid)
        region = None
        if slot.region_index is not None:
            region = ["East", "West", "South", "Midwest"][slot.region_index]
        picks.append(Pick(
            game_slot=GameSlot(game_id=gid, round=slot.round, region=region),
            team_name=team,
        ))
    return BracketEntry(
        entry_id=entry_id,
        entry_name=name,
        owner_name=owner,
        platform="espn",
        group_id=group_id,
        picks=picks,
        tiebreaker=random.randint(120, 180),
    )


def load_mock_data(store: DataStore) -> None:
    """Load two mock groups with realistic bracket entries."""
    random.seed(42)
    teams = _all_teams()
    state = TournamentState(year=2026, completed_games=[], teams=teams)
    store.set_tournament_state(state)

    # Group 1: Office Pool (12 entries)
    group1 = GroupInfo(
        group_id="mock-office-pool",
        group_name="Office Pool",
        platform="espn",
        entry_count=12,
        scoring_system="espn_standard",
    )
    entries1 = []
    for i in range(12):
        owner = FIRST_NAMES[i % len(FIRST_NAMES)]
        suffix = BRACKET_SUFFIXES[i % len(BRACKET_SUFFIXES)]
        chalk = random.uniform(0.45, 0.85)
        entries1.append(_make_entry(
            entry_id=f"office-{i+1}",
            name=f"{owner}{suffix}",
            owner=owner,
            group_id=group1.group_id,
            chalk_bias=chalk,
        ))
    store.add_group(group1, entries1)

    # Group 2: Friends League (8 entries)
    group2 = GroupInfo(
        group_id="mock-friends-league",
        group_name="Friends League",
        platform="espn",
        entry_count=8,
        scoring_system="espn_standard",
    )
    entries2 = []
    for i in range(8):
        owner = FIRST_NAMES[(i + 12) % len(FIRST_NAMES)]
        suffix = BRACKET_SUFFIXES[(i + 5) % len(BRACKET_SUFFIXES)]
        chalk = random.uniform(0.40, 0.80)
        entries2.append(_make_entry(
            entry_id=f"friends-{i+1}",
            name=f"{owner}{suffix}",
            owner=owner,
            group_id=group2.group_id,
            chalk_bias=chalk,
        ))
    store.add_group(group2, entries2)
