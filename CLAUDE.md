# March Madness Bracket Analyzer

## Project Overview

Interactive dashboard showing which bracket challenge entries are most likely to win, powered by live data scraping, NCAA basketball analytics, and Monte Carlo-style bracket simulation. Users import their bracket entries from ESPN, CBS, Yahoo (and potentially other platforms), and the system continuously projects win probabilities as the tournament progresses.

## Tech Stack

### Backend (Python + FastAPI)
- **Python 3.11+** — primary language for all backend logic
- **FastAPI** — REST API serving projection results, triggering scrapes, handling what-if requests
- **httpx** — HTTP client for ESPN's public Gambit API and Barttorvik ratings (no auth required)
- **NumPy** — vectorized trace pool simulations and standings computation
- **Pydantic** — data models and validation across all agents
- **JSON file store** — group registration persistence (`data/groups.json`), ratings cache (`data/cache/ratings/`)

### Frontend (Next.js)
- **Next.js 14+ (App Router)** — deployed on Vercel
- **Tailwind CSS** — styling
- **React client state** — what-if toggles and interactive controls
- **SWR** — data fetching from FastAPI backend

### Deployment
- **Vercel** — Next.js frontend
- **Railway or Fly.io** — FastAPI backend (Playwright may be needed for CBS/Yahoo post-MVP)

### Monorepo Structure
Frontend lives at `/frontend/`. Backend lives at `/src/`. Single CLAUDE.md governs both.

## Multi-Agent Architecture

This project uses specialized Claude Code agents defined in `.claude/agents/`. Each agent owns specific directories and responsibilities. The main Claude session acts as orchestrator, dispatching to agents as needed.

### Domain Ownership

| Agent | Owns | Role |
|-------|------|------|
| **data-orchestrator** | `/src/data/` (root only) | Coordinates scraper sub-agents, merges results, exposes unified data interface |
| **scraper-espn** | `/src/data/scrapers/espn/` | ESPN Tournament Challenge scraping |
| **scraper-cbs** | `/src/data/scrapers/cbs/` | CBS Sports bracket game scraping |
| **scraper-yahoo** | `/src/data/scrapers/yahoo/` | Yahoo bracket game scraping |
| **ncaa-data** | `/src/ncaa/` | Team stats, matchup probabilities, historical data |
| **projection-engine** | `/src/projections/` | Monte Carlo simulation, win probability calculation |
| **standings-engine** | `/src/standings/` | Group finish probabilities (1st, 2nd, 3rd, etc.) per entry |
| **user-adjustments** | `/src/adjustments/` | User override layer for projection inputs |
| **dashboard** | `/frontend/`, `/public/` | Next.js web UI, interactive controls |
| **reviewer** | Read-only across all dirs | Code review, security, data integrity audits |

### Dispatch Rules

**Parallel dispatch** — use when tasks are independent:
- All three scrapers (espn, cbs, yahoo) can run in parallel for data fetching
- ncaa-data and data-orchestrator can run in parallel when loading cached data
- reviewer can run in parallel with any other agent (read-only)

**Sequential dispatch** — use when outputs feed into inputs:
1. Scrapers -> data-orchestrator (merge results before downstream use)
2. ncaa-data -> projection-engine (matchup probs required before simulation)
3. projection-engine -> standings-engine (game-level probs required before standings calc)
4. standings-engine -> dashboard (standings/finish probs must exist before display)
5. user-adjustments -> projection-engine -> standings-engine -> dashboard (overrides re-trigger full pipeline)

**General rules:**
- Never dispatch two agents that write to the same directory simultaneously
- The orchestrator coordinates; individual scrapers never talk to each other directly
- reviewer is always safe to dispatch in parallel (read-only)

### Interface Contracts

```
Scrapers emit       -> normalized BracketEntry[] (Pydantic) to data-orchestrator
data-orchestrator   -> unified BracketEntry[] to standings-engine (entries + picks)
ncaa-data           -> MatchupProbability[] to projection-engine (AdjO/AdjD/AdjTempo → log5 win probs)
projection-engine   -> ProjectionResult[] (per-game win probs for all 63 games) to standings-engine
standings-engine    -> StandingsResult[] (finish probability distributions per entry) to dashboard
user-adjustments    -> OverridePayload (game lock-ins, P=1.0/0.0) to projection-engine → standings-engine → dashboard
```

### Simulation Strategy

- **Primary: TracePool** (`src/projections/traces.py`): Pre-compute 100k tournament traces on startup. User locks = boolean mask filter on traces. Probability overrides = importance sampling reweighting. Falls back to StandingsEngine if <500 traces survive filtering. Saved/loaded from `data/cache/trace_pool.npz`.
- **Fallback: StandingsEngine** (`src/standings/engine.py`): 32+ remaining games → MC 10k sims; ≤15 games → exact enumeration of all 2^N outcomes weighted by probability. No sampling error.
- **Matchup probabilities**: Barttorvik efficiency ratings (AdjO/AdjD via `efficiency_win_prob()`) when available, falling back to historical seed-vs-seed win rates (`seed_win_prob()`). Shared `build_matchup_fn()` in `src/ncaa/matchups.py`.
- **Scoring (MVP)**: ESPN standard — 10/20/40/80/160/320 points per correct pick in rounds 1-6.

## Build Status

All core features are implemented and working end-to-end:

1. **data-orchestrator** — Pydantic models, DataStore with persistence, group management API endpoints (add/refresh/delete)
2. **scraper-espn** — ESPN Gambit API scraping with dynamic year detection, region mapping, validated against live private groups
3. **ncaa-data** — Barttorvik ratings fetcher with name alias matching + fuzzy lookup, bracket structure, log5/efficiency matchup probabilities, shared `build_matchup_fn()` utility
4. **projection-engine** — Bracket-aware conditional game probabilities + TracePool (100k pre-computed traces with lock filtering and importance sampling)
5. **standings-engine** — MC simulation + exact enumeration + TracePool integration for instant what-if
6. **dashboard** — Next.js leaderboard UI with Add Group flow, interactive bracket, error handling
7. **user-adjustments** — Lock cascading + probability overrides
8. **reviewer** — Available for code review

**Next**: Deploy (Railway/Fly.io backend + Vercel frontend)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (groups, entries, trace pool status, ratings status) |
| GET | `/api/projections` | Baseline bracket projections (63 games + team advancement) |
| POST | `/api/projections/simulate` | What-if simulation with locks + prob overrides + optional group standings |
| GET | `/api/groups` | List all bracket groups |
| GET | `/api/groups/{group_id}` | Get a single group |
| POST | `/api/groups` | Add a group (body: `{"platform": "espn", "group_id": "..."}`) |
| POST | `/api/groups/{group_id}/refresh` | Re-fetch group from ESPN |
| DELETE | `/api/groups/{group_id}` | Remove a group |
| GET | `/api/entries/{entry_id}` | Entry detail with picks and current score |
| GET | `/api/standings/{group_id}` | Group standings with rank probability distributions |

## What-If Simulation System

- **Game locks** (`apply_locks` in `src/adjustments/overrides.py`): Locking a team at a later round auto-cascades backward through their bracket path (e.g., locking Duke at E8 also locks R64, R32, S16). Implemented by adding synthetic `GameResult` entries with `loser="LOCKED"`.
- **Probability overrides** (`prob_overrides` dict): Checked before `matchup_fn` in both `ProjectionEngine` and `StandingsEngine`. For later-round games, override is interpreted as "feeder_a side wins" probability.
- **`eligible_teams`** field on `ProjectionResult`: Populated for unconfirmed later-round games (>2 teams with prob > 1%). Used by the frontend dropdown component.

## Adding New Agents

New agents (e.g., additional scraper platforms like Splash or Sleeper) should follow the established pattern:

1. Create a new file in `.claude/agents/` following the YAML frontmatter + system prompt convention used by existing agents
2. Name scraper agents as `scraper-{platform}.md`
3. Name other agents as `{domain}.md`
4. Create the corresponding source directory under `/src/`
5. Add the agent to the domain ownership table above
6. Register the agent in the dispatch rules (scrapers are parallel by default)

<!-- Pattern: To add a new bracket platform scraper, copy scraper-espn.md, update the
     platform name/description/directory, create /src/data/scrapers/{platform}/, and
     add it to the domain ownership table and parallel scraper dispatch group above. -->
