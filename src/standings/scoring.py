"""Scoring rules for bracket challenges.

ESPN standard scoring for MVP. Designed to be pluggable for future
CBS/Yahoo support.
"""

from __future__ import annotations

from src.data.models import Round


# ESPN standard: 10/20/40/80/160/320 per correct pick
ESPN_POINTS = {
    Round.ROUND_OF_64: 10,
    Round.ROUND_OF_32: 20,
    Round.SWEET_16: 40,
    Round.ELITE_8: 80,
    Round.FINAL_4: 160,
    Round.CHAMPIONSHIP: 320,
}


def espn_score(round_val: Round) -> int:
    """Points awarded for a correct pick in a given round (ESPN standard)."""
    return ESPN_POINTS[round_val]


def score_entry(
    picks: dict[int, str],
    outcomes: dict[int, str],
    game_rounds: dict[int, Round],
) -> int:
    """Score a bracket entry against a set of game outcomes.

    Args:
        picks: {game_id: team_name_picked} — the entry's picks.
        outcomes: {game_id: winning_team_name} — actual or simulated results.
        game_rounds: {game_id: Round} — which round each game belongs to.

    Returns:
        Total score under ESPN standard rules.
    """
    total = 0
    for gid, winner in outcomes.items():
        picked = picks.get(gid)
        if picked and picked == winner:
            round_val = game_rounds[gid]
            total += espn_score(round_val)
    return total
