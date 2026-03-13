"""FastAPI application — serves bracket data, projections, and standings."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.data.store import DataStore
from src.data.router import create_data_router, fetch_espn_group
from src.standings.router import create_standings_router
from src.projections.router import create_projections_router
from src.projections.traces import TracePool
from src.ncaa.bracket import build_bracket
from src.ncaa.matchups import build_matchup_fn
from src.ncaa.ratings import RatingsProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REGION_NAMES = ["East", "West", "South", "Midwest"]
TRACE_POOL_PATH = Path("data/cache/trace_pool.npz")
TRACE_POOL_SIZE = 100_000


def regenerate_trace_pool(store: DataStore) -> None:
    """Generate (or reload) the trace pool based on current tournament state."""
    state = store.get_tournament_state()
    if not state.teams:
        logger.info("No teams loaded, skipping trace pool generation")
        return

    bracket = build_bracket(REGION_NAMES)
    matchup_fn = build_matchup_fn(state, store.ratings)

    pool = TracePool(bracket, matchup_fn, state)

    # Try loading from disk first
    if pool.load(TRACE_POOL_PATH):
        store.trace_pool = pool
        return

    # Generate fresh traces
    if state.games_remaining > 0:
        logger.info("Generating %d traces for %d remaining games...",
                     TRACE_POOL_SIZE, state.games_remaining)
        pool.generate(n_traces=TRACE_POOL_SIZE)
        pool.save(TRACE_POOL_PATH)
        store.trace_pool = pool
        logger.info("Trace pool ready")


app = FastAPI(title="March Madness Bracket Analyzer")

cors_origins = [
    "http://localhost:3000",
]
# Add production frontend URL if set
if os.environ.get("FRONTEND_URL"):
    cors_origins.append(os.environ["FRONTEND_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared data store
store = DataStore()

# Load Barttorvik ratings
ratings = RatingsProvider()
if ratings.load_or_fetch():
    logger.info("Ratings loaded: %d teams", len(ratings.all_teams()))
    store.ratings = ratings
else:
    logger.warning("No Barttorvik ratings available — using seed-based probabilities")

# Load saved groups from disk on startup
saved = DataStore.load_group_registrations()
for reg in saved:
    if reg.get("platform") == "espn":
        try:
            fetch_espn_group(reg["group_id"], store)
        except Exception:
            logger.warning("Failed to reload group %s on startup", reg["group_id"])

# Generate trace pool after loading tournament data
regenerate_trace_pool(store)

app.include_router(
    create_data_router(store, on_state_changed=lambda: regenerate_trace_pool(store)),
    prefix="/api",
)
app.include_router(create_standings_router(store), prefix="/api")
app.include_router(create_projections_router(store), prefix="/api")


@app.get("/api/health")
def health():
    pool_info = None
    if store.trace_pool and store.trace_pool.is_generated:
        pool_info = {
            "n_traces": store.trace_pool.n_traces,
            "n_remaining_games": store.trace_pool.n_remaining,
        }
    return {
        "status": "ok",
        "groups": len(store.list_groups()),
        "entries": store.total_entries,
        "trace_pool": pool_info,
        "ratings": store.ratings is not None and store.ratings.is_loaded,
    }
