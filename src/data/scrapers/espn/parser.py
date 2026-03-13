"""Parse ESPN Tournament Challenge API responses into normalized Pydantic models.

Maps ESPN's UUID-based proposition/outcome system to our models:
  - Each of the 63 games is a "proposition" with a unique propositionId
  - Each proposition has possibleOutcomes with outcomeIds mapping to teams
  - Each entry's 63 picks reference (propositionId, outcomeId) pairs

Proposition structure by round:
  R64 (period 1): 32 props, 2 outcomes each (the 2 teams playing)
  R32 (period 2): 16 props, 4 outcomes each (possible teams from feeder games)
  S16 (period 3): 8 props, 8 outcomes each
  E8  (period 4): 4 props, 16 outcomes each
  F4  (period 5): 2 props, 32 outcomes each
  NCG (period 6): 1 prop, 64 outcomes
"""

from __future__ import annotations

from src.data.models import (
    BracketEntry,
    GameSlot,
    GroupInfo,
    Pick,
    Round,
    Team,
    GameResult,
    TournamentState,
)


class ESPNParser:
    """Converts ESPN API data into normalized Pydantic models."""

    def __init__(self, all_propositions: list[dict],
                 region_map: dict[int, str] | None = None,
                 year: int = 2026):
        """Initialize with the full list of 63 propositions.

        Args:
            all_propositions: Output of ESPNClient.fetch_all_propositions().
                Each prop must have a '_round' field (1-6).
            region_map: Mapping of ESPN regionId (int) to region name string.
                e.g. {1: "South", 2: "West", 3: "East", 4: "Midwest"}.
                Obtained from challenge root settings.regionNames.
            year: Tournament year.
        """
        self._propositions = all_propositions
        self._region_map = region_map or {}
        self._year = year

        # Build lookup tables
        self._outcome_to_team: dict[str, str] = {}  # outcomeId -> team name
        self._outcome_to_seed: dict[str, int] = {}
        self._outcome_to_region: dict[str, int] = {}
        self._prop_to_game_id: dict[str, int] = {}  # propositionId -> game_id (1-63)
        self._prop_to_round: dict[str, Round] = {}
        self._prop_by_id: dict[str, dict] = {}

        self._build_lookups()

    def _build_lookups(self):
        """Build all lookup tables from proposition data."""
        # Sort: by round, then by proposition name for consistent game_id ordering
        sorted_props = sorted(
            self._propositions,
            key=lambda p: (p.get("_round", 0), p.get("name", "")),
        )

        for game_id, prop in enumerate(sorted_props, start=1):
            pid = prop["id"]
            self._prop_by_id[pid] = prop
            self._prop_to_game_id[pid] = game_id
            self._prop_to_round[pid] = Round(prop["_round"])

            # Map all possible outcomes for this game to team info
            for outcome in prop.get("possibleOutcomes", []):
                oid = outcome["id"]
                self._outcome_to_team[oid] = outcome.get("name", "Unknown")
                self._outcome_to_seed[oid] = outcome.get("regionSeed", 0)
                self._outcome_to_region[oid] = outcome.get("regionId", 0)

    @property
    def game_count(self) -> int:
        return len(self._propositions)

    def outcome_team(self, outcome_id: str) -> str:
        """Look up team name for an outcome ID."""
        return self._outcome_to_team.get(outcome_id, "Unknown")

    def get_teams(self) -> list[Team]:
        """Extract all 64 tournament teams from Round 1 propositions."""
        teams = []
        seen = set()
        for prop in self._propositions:
            if prop.get("_round") != 1:
                continue
            for outcome in prop.get("possibleOutcomes", []):
                name = outcome.get("name", "Unknown")
                if name in seen:
                    continue
                seen.add(name)
                region_id = outcome.get("regionId", 0)
                region_name = self._region_map.get(region_id, str(region_id))
                teams.append(Team(
                    name=name,
                    seed=outcome.get("regionSeed", 0),
                    region=region_name,
                ))
        return teams

    def parse_group_info(self, group_data: dict) -> GroupInfo:
        """Parse group metadata from ESPN group API response."""
        settings = group_data.get("groupSettings", {})
        return GroupInfo(
            group_id=str(group_data.get("groupId", "")),
            group_name=settings.get("name", "Unknown Group"),
            platform="espn",
            entry_count=group_data.get("size", 0),
            scoring_system="espn_standard",
        )

    def parse_entries(self, group_data: dict, group_id: str) -> list[BracketEntry]:
        """Parse all bracket entries from an ESPN group response."""
        entries = []
        for entry_data in group_data.get("entries", []):
            entry = self._parse_single_entry(entry_data, group_id)
            if entry:
                entries.append(entry)
        return entries

    def _parse_single_entry(self, entry_data: dict, group_id: str) -> BracketEntry | None:
        """Parse a single ESPN bracket entry into our model."""
        member = entry_data.get("member", {})
        picks_raw = entry_data.get("picks", [])

        picks = []
        for pick_data in picks_raw:
            prop_id = pick_data.get("propositionId", "")
            outcomes_picked = pick_data.get("outcomesPicked", [])

            if not prop_id or not outcomes_picked:
                continue

            outcome_id = outcomes_picked[0].get("outcomeId", "")
            team_name = self._outcome_to_team.get(outcome_id, "Unknown")
            game_id = self._prop_to_game_id.get(prop_id)
            round_val = self._prop_to_round.get(prop_id)

            if game_id is None or round_val is None:
                continue

            # Region from the proposition's outcomes
            region = None
            if round_val.value <= 4:
                region_id = self._outcome_to_region.get(outcome_id, 0)
                region = self._region_map.get(region_id, str(region_id))

            picks.append(Pick(
                game_slot=GameSlot(
                    game_id=game_id,
                    round=round_val,
                    region=region,
                ),
                team_name=team_name,
            ))

        if not picks:
            return None

        # Extract tiebreaker
        tiebreaker = None
        tie_answers = entry_data.get("tiebreakAnswers", [])
        if tie_answers:
            try:
                tiebreaker = int(tie_answers[0])
            except (ValueError, TypeError, IndexError):
                pass

        return BracketEntry(
            entry_id=str(entry_data.get("id", "")),
            entry_name=entry_data.get("name", "Unnamed"),
            owner_name=member.get("displayName", "Unknown"),
            platform="espn",
            group_id=group_id,
            picks=picks,
            tiebreaker=tiebreaker,
        )

    def parse_tournament_state(self) -> TournamentState:
        """Build current tournament state from completed propositions."""
        completed = []
        for prop in self._propositions:
            if prop.get("status") != "COMPLETE":
                continue

            correct_outcomes = prop.get("correctOutcomes", [])
            actual_ids = prop.get("actualOutcomeIds", [])
            if not correct_outcomes and not actual_ids:
                continue

            # Get winner — correctOutcomes and actualOutcomeIds are both lists of ID strings
            if correct_outcomes:
                winner_id = correct_outcomes[0] if isinstance(correct_outcomes[0], str) else correct_outcomes[0].get("id", "")
            else:
                winner_id = actual_ids[0] if actual_ids else ""

            winner_name = self._outcome_to_team.get(winner_id, "Unknown")

            # Find the loser (the other outcome in R1 games)
            all_outcomes = prop.get("possibleOutcomes", [])
            loser_name = "Unknown"
            winner_score = None
            loser_score = None

            for o in all_outcomes:
                score = o.get("score")
                if o["id"] == winner_id:
                    if score is not None:
                        winner_score = int(score)
                elif o.get("regionSeed") and prop.get("_round") == 1:
                    # In R1, the other team is the loser
                    loser_name = o.get("name", "Unknown")
                    if score is not None:
                        loser_score = int(score)

            game_id = self._prop_to_game_id.get(prop["id"])
            round_val = self._prop_to_round.get(prop["id"])
            if game_id is None or round_val is None:
                continue

            completed.append(GameResult(
                game_slot=GameSlot(game_id=game_id, round=round_val),
                winner=winner_name,
                loser=loser_name,
                winner_score=winner_score,
                loser_score=loser_score,
            ))

        return TournamentState(
            year=self._year,
            completed_games=completed,
            teams=self.get_teams(),
        )
