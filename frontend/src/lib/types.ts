/** TypeScript types matching the Python Pydantic models. */

export interface StandingsResult {
  entry_id: string;
  entry_name: string;
  current_score: number;
  expected_final_score: number;
  rank_probabilities: Record<number, number>;
  top_3_prob: number;
  top_5_prob: number;
}

export interface GroupInfo {
  group_id: string;
  group_name: string;
  platform: string;
  entry_count: number;
  scoring_system: string;
}

export interface GroupStandings {
  group: GroupInfo;
  standings: StandingsResult[];
  games_remaining: number;
  last_updated: string;
}

export interface TeamProb {
  team: string;
  prob: number;
}

export interface ProjectionResult {
  game_id: number;
  round: number;
  team_a: string;
  team_b: string;
  prob_a_wins: number;
  is_completed: boolean;
  eligible_teams: TeamProb[] | null;
}

export interface BracketPick {
  game_id: number;
  round: number;
  team_name: string;
  is_correct: boolean | null; // null if game not yet played
}

export interface EntryDetail {
  entry_id: string;
  entry_name: string;
  owner_name: string;
  current_score: number;
  picks: BracketPick[];
}

export interface AdvancementEntry {
  team: string;
  seed: number;
  region: string;
  probabilities: Record<number, number>; // round_value -> probability
}

export interface ProjectionsResponse {
  projections: ProjectionResult[];
  advancement: AdvancementEntry[];
  games_remaining: number;
  last_updated: string;
}

export interface GameLock {
  game_id: number;
  winner: string;
}

export interface ProbabilityOverride {
  game_id: number;
  prob_a_wins: number;
}

export interface SimulateRequest {
  locks: GameLock[];
  probability_overrides: ProbabilityOverride[];
  group_id?: string;
}

export interface SimulateResponse {
  projections: ProjectionResult[];
  advancement: AdvancementEntry[];
  standings: StandingsResult[] | null;
  games_remaining: number;
}
