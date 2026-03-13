"""Tests for NCAA tournament bracket structure."""

import pytest

from src.data.models import Round
from src.ncaa.bracket import build_bracket, BracketSlot, R64_SEED_MATCHUPS


@pytest.fixture
def bracket():
    return build_bracket(["East", "West", "South", "Midwest"])


class TestBracketStructure:
    """Verify the 63-game bracket topology is correctly wired."""

    def test_total_games(self, bracket):
        assert len(bracket.slots) == 63

    def test_games_per_round(self, bracket):
        assert len(bracket.games_in_round(Round.ROUND_OF_64)) == 32
        assert len(bracket.games_in_round(Round.ROUND_OF_32)) == 16
        assert len(bracket.games_in_round(Round.SWEET_16)) == 8
        assert len(bracket.games_in_round(Round.ELITE_8)) == 4
        assert len(bracket.games_in_round(Round.FINAL_4)) == 2
        assert len(bracket.games_in_round(Round.CHAMPIONSHIP)) == 1

    def test_games_per_region(self, bracket):
        for region_idx in range(4):
            games = bracket.region_games(region_idx)
            assert len(games) == 15  # 8 + 4 + 2 + 1

    def test_r64_have_no_feeders(self, bracket):
        for gid in bracket.games_in_round(Round.ROUND_OF_64):
            assert bracket.feeders(gid) is None

    def test_r64_have_seed_matchups(self, bracket):
        for gid in bracket.games_in_round(Round.ROUND_OF_64):
            slot = bracket.slot(gid)
            assert slot.seed_matchup is not None
            assert slot.seed_matchup in R64_SEED_MATCHUPS

    def test_later_rounds_have_feeders(self, bracket):
        for round_val in [Round.ROUND_OF_32, Round.SWEET_16, Round.ELITE_8,
                          Round.FINAL_4, Round.CHAMPIONSHIP]:
            for gid in bracket.games_in_round(round_val):
                feeders = bracket.feeders(gid)
                assert feeders is not None
                assert len(feeders) == 2
                # Both feeder games should exist
                assert feeders[0] in bracket.slots
                assert feeders[1] in bracket.slots

    def test_championship_has_no_next(self, bracket):
        assert bracket.advances_to(63) is None

    def test_every_non_championship_advances(self, bracket):
        for gid in range(1, 63):
            next_game = bracket.advances_to(gid)
            assert next_game is not None, f"Game {gid} should advance somewhere"
            assert next_game in bracket.slots

    def test_feeder_consistency(self, bracket):
        """Every game's feeds_into should reference a game that lists it as a feeder."""
        for gid, slot in bracket.slots.items():
            if slot.feeds_into is not None:
                next_slot = bracket.slot(slot.feeds_into)
                assert next_slot.feeder_game_ids is not None
                assert gid in next_slot.feeder_game_ids, \
                    f"Game {gid} feeds into {slot.feeds_into}, but {slot.feeds_into} " \
                    f"doesn't list {gid} as a feeder"

    def test_r64_seed_matchup_coverage(self, bracket):
        """Each region should have all 8 standard seed matchups."""
        for region_idx in range(4):
            r64_games = [
                gid for gid in bracket.games_in_round(Round.ROUND_OF_64)
                if bracket.slot(gid).region_index == region_idx
            ]
            matchups = {bracket.slot(gid).seed_matchup for gid in r64_games}
            assert matchups == set(R64_SEED_MATCHUPS)


class TestBracketNavigation:

    def test_path_to_championship_from_r64(self, bracket):
        # Game 1 is R64 in region 0
        path = bracket.path_to_championship(1)
        assert path[0] == 1
        assert path[-1] == 63
        # R64 → R32 → S16 → E8 → F4 → NCG = 6 games
        assert len(path) == 6

    def test_path_from_championship(self, bracket):
        path = bracket.path_to_championship(63)
        assert path == [63]

    def test_path_from_f4(self, bracket):
        path = bracket.path_to_championship(61)
        assert path == [61, 63]

    def test_possible_seeds_r64(self, bracket):
        # Game 1 is 1 vs 16
        seeds = bracket.possible_seeds(1)
        assert seeds == [(1, 16)]

    def test_possible_seeds_r32(self, bracket):
        # R32 game 33 is fed by games 1 (1v16) and 2 (8v9)
        seeds = bracket.possible_seeds(33)
        # All combinations: (1,8), (1,9), (16,8), (16,9)
        assert len(seeds) == 4
        assert (1, 8) in seeds
        assert (1, 9) in seeds
        assert (16, 8) in seeds
        assert (16, 9) in seeds

    def test_reachable_seeds_grows_with_rounds(self, bracket):
        # Each round doubles the number of reachable seeds
        r64_seeds = bracket._reachable_seeds(1)
        assert len(r64_seeds) == 2  # 1 and 16

        r32_seeds = bracket._reachable_seeds(33)
        assert len(r32_seeds) == 4  # 1, 16, 8, 9

        s16_seeds = bracket._reachable_seeds(49)
        assert len(s16_seeds) == 8

        e8_seeds = bracket._reachable_seeds(57)
        assert len(e8_seeds) == 16


class TestBracketSlotProperties:

    def test_is_r64(self, bracket):
        assert bracket.slot(1).is_r64
        assert not bracket.slot(33).is_r64
        assert not bracket.slot(63).is_r64

    def test_is_national(self, bracket):
        # R64 through E8 are regional
        assert not bracket.slot(1).is_national
        assert not bracket.slot(57).is_national
        # F4 and NCG are national
        assert bracket.slot(61).is_national
        assert bracket.slot(63).is_national

    def test_region_names(self, bracket):
        assert bracket.region_names == ["East", "West", "South", "Midwest"]


class TestFinalFourWiring:

    def test_ff_game_61_feeders(self, bracket):
        """F4 game 61 should be fed by E8 games from regions 0 and 1."""
        feeders = bracket.feeders(61)
        assert feeders == (57, 58)
        assert bracket.slot(57).region_index == 0
        assert bracket.slot(58).region_index == 1

    def test_ff_game_62_feeders(self, bracket):
        """F4 game 62 should be fed by E8 games from regions 2 and 3."""
        feeders = bracket.feeders(62)
        assert feeders == (59, 60)
        assert bracket.slot(59).region_index == 2
        assert bracket.slot(60).region_index == 3

    def test_championship_feeders(self, bracket):
        feeders = bracket.feeders(63)
        assert feeders == (61, 62)
