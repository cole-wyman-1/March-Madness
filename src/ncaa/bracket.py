"""NCAA Tournament bracket structure — 63-game topology.

Defines the canonical bracket layout: 4 regions × 15 games + 3 national games = 63.
Every game knows its round, region, feeder games, and seed matchup.

Game ID scheme (canonical):
  Region 1: R64 games 1-8,   R32 games 33-36, S16 games 49-50, E8 game 57
  Region 2: R64 games 9-16,  R32 games 37-40, S16 games 51-52, E8 game 58
  Region 3: R64 games 17-24, R32 games 41-44, S16 games 53-54, E8 game 59
  Region 4: R64 games 25-32, R32 games 45-48, S16 games 55-56, E8 game 60
  Final Four: games 61 (R1 vs R2), 62 (R3 vs R4)
  Championship: game 63

Seed matchups within each region's R64 (standard NCAA bracket):
  Game 1: 1 vs 16    Game 5: 6 vs 11
  Game 2: 8 vs 9     Game 6: 3 vs 14
  Game 3: 5 vs 12    Game 7: 7 vs 10
  Game 4: 4 vs 13    Game 8: 2 vs 15
"""

from __future__ import annotations

from dataclasses import dataclass, field
from src.data.models import Round


# Standard seed matchups for R64 (within each region, 8 games)
# Order: (high_seed, low_seed)
R64_SEED_MATCHUPS: list[tuple[int, int]] = [
    (1, 16),
    (8, 9),
    (5, 12),
    (4, 13),
    (6, 11),
    (3, 14),
    (7, 10),
    (2, 15),
]

# Region names — the actual names change per year, so we use indices 0-3
# and map to names when loading tournament data
DEFAULT_REGION_NAMES = ["Region 1", "Region 2", "Region 3", "Region 4"]

# Final Four pairing: which regions play each other
# Standard: Region 1 vs Region 2, Region 3 vs Region 4
FF_PAIRINGS = [(0, 1), (2, 3)]


@dataclass(frozen=True)
class BracketSlot:
    """A single game slot in the bracket."""

    game_id: int  # 1-63
    round: Round
    region_index: int | None  # 0-3, None for F4/NCG
    seed_matchup: tuple[int, int] | None  # (high_seed, low_seed) for R64 only
    feeder_game_ids: tuple[int, int] | None  # (game_a, game_b) — None for R64
    feeds_into: int | None  # game_id of the next round, None for NCG

    @property
    def is_r64(self) -> bool:
        return self.round == Round.ROUND_OF_64

    @property
    def is_national(self) -> bool:
        """True for Final Four and Championship games."""
        return self.region_index is None


@dataclass
class Bracket:
    """Full 63-game tournament bracket.

    Provides efficient lookups for bracket navigation:
    - slot(game_id) → BracketSlot
    - feeders(game_id) → pair of feeder game_ids
    - advances_to(game_id) → next game_id
    - region_games(region_index) → all 15 game_ids in a region
    - possible_seeds(game_id) → which seeds could reach this game
    """

    slots: dict[int, BracketSlot] = field(default_factory=dict)
    region_names: list[str] = field(default_factory=lambda: list(DEFAULT_REGION_NAMES))

    def slot(self, game_id: int) -> BracketSlot:
        """Get the bracket slot for a game ID."""
        return self.slots[game_id]

    def feeders(self, game_id: int) -> tuple[int, int] | None:
        """Get the two feeder game IDs, or None for R64 games."""
        return self.slots[game_id].feeder_game_ids

    def advances_to(self, game_id: int) -> int | None:
        """Get the game ID that this game's winner advances to."""
        return self.slots[game_id].feeds_into

    def region_games(self, region_index: int) -> list[int]:
        """Get all 15 game IDs in a region, ordered by round then game."""
        return sorted(
            gid for gid, s in self.slots.items()
            if s.region_index == region_index
        )

    def games_in_round(self, round_val: Round) -> list[int]:
        """Get all game IDs in a specific round."""
        return sorted(
            gid for gid, s in self.slots.items()
            if s.round == round_val
        )

    def possible_seeds(self, game_id: int) -> list[tuple[int, int]]:
        """Return all possible seed matchups that could occur at this game slot.

        For R64: returns a single matchup, e.g. [(1, 16)].
        For R32: returns matchups like [(1, 8), (1, 9), (16, 8), (16, 9)].
        Later rounds have more combinations.
        """
        slot = self.slots[game_id]
        if slot.seed_matchup:
            return [slot.seed_matchup]

        if slot.feeder_game_ids is None:
            return []

        # Recursively get possible seeds from each feeder
        seeds_a = self._reachable_seeds(slot.feeder_game_ids[0])
        seeds_b = self._reachable_seeds(slot.feeder_game_ids[1])
        return [(a, b) for a in seeds_a for b in seeds_b]

    def _reachable_seeds(self, game_id: int) -> list[int]:
        """Get all seeds that could potentially reach (win) this game."""
        slot = self.slots[game_id]
        if slot.seed_matchup:
            return list(slot.seed_matchup)

        if slot.feeder_game_ids is None:
            return []

        seeds = []
        for fid in slot.feeder_game_ids:
            seeds.extend(self._reachable_seeds(fid))
        return seeds

    def path_to_championship(self, game_id: int) -> list[int]:
        """Get the sequence of game IDs from this game to the championship."""
        path = [game_id]
        current = game_id
        while True:
            next_game = self.advances_to(current)
            if next_game is None:
                break
            path.append(next_game)
            current = next_game
        return path


def build_bracket(region_names: list[str] | None = None) -> Bracket:
    """Construct the standard 63-game NCAA tournament bracket.

    Args:
        region_names: Optional list of 4 region names (e.g. ["East", "West", "South", "Midwest"]).

    Returns:
        A fully-wired Bracket with all 63 slots.
    """
    slots: dict[int, BracketSlot] = {}
    names = region_names or list(DEFAULT_REGION_NAMES)

    for region_idx in range(4):
        _build_region(slots, region_idx)

    _build_final_rounds(slots)

    bracket = Bracket(slots=slots, region_names=names)

    # Sanity check
    assert len(bracket.slots) == 63, f"Expected 63 slots, got {len(bracket.slots)}"
    return bracket


def _build_region(slots: dict[int, BracketSlot], region_idx: int) -> None:
    """Build all 15 game slots for a single region."""
    # Base offsets for each round within this region
    r64_base = region_idx * 8 + 1        # games 1, 9, 17, 25
    r32_base = 33 + region_idx * 4       # games 33, 37, 41, 45
    s16_base = 49 + region_idx * 2       # games 49, 51, 53, 55
    e8_base = 57 + region_idx            # games 57, 58, 59, 60

    # R64: 8 games per region
    r64_ids = list(range(r64_base, r64_base + 8))
    for i, gid in enumerate(r64_ids):
        slots[gid] = BracketSlot(
            game_id=gid,
            round=Round.ROUND_OF_64,
            region_index=region_idx,
            seed_matchup=R64_SEED_MATCHUPS[i],
            feeder_game_ids=None,
            feeds_into=r32_base + i // 2,
        )

    # R32: 4 games per region, each fed by 2 R64 games
    r32_ids = list(range(r32_base, r32_base + 4))
    for i, gid in enumerate(r32_ids):
        feeders = (r64_ids[i * 2], r64_ids[i * 2 + 1])
        slots[gid] = BracketSlot(
            game_id=gid,
            round=Round.ROUND_OF_32,
            region_index=region_idx,
            seed_matchup=None,
            feeder_game_ids=feeders,
            feeds_into=s16_base + i // 2,
        )

    # S16: 2 games per region
    s16_ids = list(range(s16_base, s16_base + 2))
    for i, gid in enumerate(s16_ids):
        feeders = (r32_ids[i * 2], r32_ids[i * 2 + 1])
        slots[gid] = BracketSlot(
            game_id=gid,
            round=Round.SWEET_16,
            region_index=region_idx,
            seed_matchup=None,
            feeder_game_ids=feeders,
            feeds_into=e8_base,
        )

    # E8: 1 game per region
    slots[e8_base] = BracketSlot(
        game_id=e8_base,
        round=Round.ELITE_8,
        region_index=region_idx,
        seed_matchup=None,
        feeder_game_ids=(s16_ids[0], s16_ids[1]),
        feeds_into=61 + region_idx // 2,  # F4 game 61 or 62
    )


def _build_final_rounds(slots: dict[int, BracketSlot]) -> None:
    """Build Final Four (61, 62) and Championship (63)."""
    # Final Four game 61: Region 1 (E8=57) vs Region 2 (E8=58)
    slots[61] = BracketSlot(
        game_id=61,
        round=Round.FINAL_4,
        region_index=None,
        seed_matchup=None,
        feeder_game_ids=(57, 58),
        feeds_into=63,
    )

    # Final Four game 62: Region 3 (E8=59) vs Region 4 (E8=60)
    slots[62] = BracketSlot(
        game_id=62,
        round=Round.FINAL_4,
        region_index=None,
        seed_matchup=None,
        feeder_game_ids=(59, 60),
        feeds_into=63,
    )

    # Championship game 63
    slots[63] = BracketSlot(
        game_id=63,
        round=Round.CHAMPIONSHIP,
        region_index=None,
        seed_matchup=None,
        feeder_game_ids=(61, 62),
        feeds_into=None,
    )
