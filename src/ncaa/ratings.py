"""Team ratings from Barttorvik (barttorvik.com).

Provides team efficiency ratings (AdjO, AdjD, AdjTempo) used by the
matchup probability functions for more accurate win probabilities than
seed-based estimates.

Data sources (in priority order):
1. Barttorvik JSON API — fetched via httpx, cached to disk
2. Manual JSON file — user can prepare data/cache/ratings/ratings_YYYY.json
3. Fallback — seed-based probabilities if no ratings available

Barttorvik API returns an array of arrays:
  [rank, team, conf, record, adjoe, adjde, barthag, efg_o, efg_d,
   to_rate, to_rate_d, orb_rate, drb_rate, ftr, ftrd, 2pt%, 2pt%d,
   3pt%, 3pt%d, adj_t, wab, ...]
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache/ratings")

# Barttorvik JSON API endpoint
BARTTORVIK_URL = "https://barttorvik.com/trank.php"

# Common name mismatches: ESPN name -> Barttorvik name
# Extended as needed when real data is tested
NAME_ALIASES: dict[str, str] = {
    "UConn": "Connecticut",
    "UCONN": "Connecticut",
    "UNC": "North Carolina",
    "USC": "Southern California",
    "LSU": "Louisiana St.",
    "SMU": "Southern Methodist",
    "UCF": "Central Florida",
    "UNLV": "Nevada Las Vegas",
    "VCU": "Virginia Commonwealth",
    "BYU": "Brigham Young",
    "TCU": "Texas Christian",
    "FAU": "Florida Atlantic",
    "UAB": "Alabama Birmingham",
    "UTEP": "Texas El Paso",
    "UTSA": "Texas San Antonio",
    "UIC": "Illinois Chicago",
    "UMBC": "Maryland Baltimore County",
    "UNCW": "UNC Wilmington",
    "UNCG": "UNC Greensboro",
    "UC Irvine": "UC Irvine",
    "UC Santa Barbara": "UC Santa Barbara",
    "St. John's": "St. John's",
    "Saint Mary's": "Saint Mary's",
}


@dataclass
class TeamRating:
    """Barttorvik-style team efficiency rating."""

    name: str
    seed: int | None = None
    region: str | None = None

    # Adjusted efficiency ratings (points per 100 possessions)
    adj_o: float = 100.0   # offensive efficiency (D1 avg ~ 100)
    adj_d: float = 100.0   # defensive efficiency (lower is better)
    adj_tempo: float = 68.0  # possessions per game

    # Derived
    @property
    def adj_em(self) -> float:
        """Adjusted efficiency margin (AdjO - AdjD). Higher is better."""
        return self.adj_o - self.adj_d

    @property
    def pythag_win_pct(self) -> float:
        """Pythagorean win percentage estimate.

        Uses the formula: O^11.5 / (O^11.5 + D^11.5)
        where 11.5 is the empirically-calibrated exponent for college basketball.
        """
        if self.adj_o <= 0:
            return 0.0
        exp = 11.5
        o_pow = self.adj_o ** exp
        d_pow = self.adj_d ** exp
        if o_pow + d_pow == 0:
            return 0.5
        return o_pow / (o_pow + d_pow)


def _normalize_name(name: str) -> str:
    """Normalize a team name for fuzzy matching."""
    s = name.strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("St.", "St").replace("State", "St")
    return s.lower()


class RatingsProvider:
    """Loads and caches team ratings from Barttorvik or a local file."""

    def __init__(self):
        self._ratings: dict[str, TeamRating] = {}
        # Normalized name -> canonical name for fuzzy lookup
        self._name_index: dict[str, str] = {}

    @property
    def is_loaded(self) -> bool:
        return len(self._ratings) > 0

    def get(self, team_name: str) -> TeamRating | None:
        """Look up a team's rating by name (with fuzzy matching)."""
        # Exact match
        if team_name in self._ratings:
            return self._ratings[team_name]

        # Try alias
        alias = NAME_ALIASES.get(team_name)
        if alias and alias in self._ratings:
            return self._ratings[alias]

        # Fuzzy match via normalized index
        norm = _normalize_name(team_name)
        canonical = self._name_index.get(norm)
        if canonical:
            return self._ratings.get(canonical)

        return None

    def all_teams(self) -> list[TeamRating]:
        """Get all loaded team ratings."""
        return list(self._ratings.values())

    def _rebuild_index(self) -> None:
        """Rebuild the normalized name index."""
        self._name_index.clear()
        for name in self._ratings:
            self._name_index[_normalize_name(name)] = name

    def load_from_dict(self, data: dict[str, dict]) -> None:
        """Load ratings from a dictionary.

        Args:
            data: {team_name: {adj_o, adj_d, adj_tempo, seed, region}}
        """
        self._ratings.clear()
        for name, vals in data.items():
            self._ratings[name] = TeamRating(
                name=name,
                seed=vals.get("seed"),
                region=vals.get("region"),
                adj_o=vals.get("adj_o", 100.0),
                adj_d=vals.get("adj_d", 100.0),
                adj_tempo=vals.get("adj_tempo", 68.0),
            )
        self._rebuild_index()

    def load_from_file(self, path: Path | str) -> bool:
        """Load ratings from a JSON file. Returns True if successful."""
        path = Path(path)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text())
            self.load_from_dict(data)
            logger.info("Loaded %d team ratings from %s", len(self._ratings), path)
            return True
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load ratings from %s: %s", path, e)
            return False

    def save_to_file(self, path: Path | str) -> None:
        """Save current ratings to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for name, r in self._ratings.items():
            data[name] = {
                "adj_o": r.adj_o,
                "adj_d": r.adj_d,
                "adj_tempo": r.adj_tempo,
                "seed": r.seed,
                "region": r.region,
            }
        path.write_text(json.dumps(data, indent=2))

    def cache_path(self, year: int) -> Path:
        """Get the cache file path for a given year."""
        return CACHE_DIR / f"ratings_{year}.json"

    # ------------------------------------------------------------------
    # Barttorvik fetching
    # ------------------------------------------------------------------

    def fetch_from_barttorvik(self, year: int = 2025) -> bool:
        """Fetch current ratings from barttorvik.com.

        Barttorvik's trank.php?json=1 returns an array of arrays:
          [rank, team, conf, record, adjoe, adjde, barthag, ...]
          Index 0: rank (int)
          Index 1: team name (str)
          Index 4: AdjOE (float)
          Index 5: AdjDE (float)
          Index 19: AdjT / tempo (float)

        Returns True if successful, False otherwise.
        """
        # Check cache first
        cached = self.cache_path(year)
        if self.load_from_file(cached):
            return True

        try:
            resp = httpx.get(
                BARTTORVIK_URL,
                params={
                    "year": year,
                    "conlimit": "All",
                    "json": "1",
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                    "Referer": "https://barttorvik.com/",
                },
                timeout=15.0,
                follow_redirects=True,
            )
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            logger.warning("Failed to fetch from Barttorvik: %s", e)
            return False

        if not isinstance(raw, list) or len(raw) == 0:
            logger.warning("Unexpected Barttorvik response format")
            return False

        self._ratings.clear()
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 20:
                continue
            try:
                name = str(row[1]).strip()
                adj_o = float(row[4])
                adj_d = float(row[5])
                adj_t = float(row[19])
                self._ratings[name] = TeamRating(
                    name=name,
                    adj_o=adj_o,
                    adj_d=adj_d,
                    adj_tempo=adj_t,
                )
            except (ValueError, TypeError, IndexError):
                continue

        self._rebuild_index()

        if self._ratings:
            self.save_to_file(cached)
            logger.info(
                "Fetched %d team ratings from Barttorvik for %d",
                len(self._ratings), year,
            )
            return True

        logger.warning("No ratings parsed from Barttorvik response")
        return False

    def load_or_fetch(self, year: int = 2025) -> bool:
        """Try to load ratings: cached file first, then Barttorvik API.

        Returns True if ratings are available.
        """
        # Try cached file
        if self.load_from_file(self.cache_path(year)):
            return True

        # Try fetching from Barttorvik
        return self.fetch_from_barttorvik(year)
