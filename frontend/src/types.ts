// Mirrors backend/app/schemas.py (MatchOut) and backend/app/ws.py (protocol).

export type MatchStatus = "waiting" | "active" | "finished" | "abandoned";

export interface Player {
  id: string;
  name: string;
  kind: string;
  joined: boolean;
}

export interface Move {
  player_id: string;
  pile: number;
  count: number;
  piles_after: number[];
  auto: boolean;
  reasoning: string | null;
  meta?: MoveMeta | null;
}

/** How an agent produced a move (LLM agents only). */
export interface MoveMeta {
  model: string;
  mode: string;
  seconds: number;
  calls: number;
  retries: number;
  fell_back: boolean;
  tool_calls: number;
  tokens_in: number;
  tokens_out: number;
}

export interface Match {
  id: string;
  status: MatchStatus;
  max_take: number | null;
  last_stone_loses: boolean;
  turn_timeout: number | null;
  turn_time_left: number | null;
  initial_piles: number[];
  piles: number[];
  players: Player[];
  current_player_id: string | null;
  winner_id: string | null;
  moves: Move[];
}

export type ServerMessage =
  | { type: "state"; match: Match }
  | { type: "game_over"; winner_id: string }
  | { type: "error"; reason: string; message: string };

export interface CreateMatchRequest {
  piles: number[];
  players: { id: string; kind?: string }[];
  agent_move_delay?: number | null;
  max_take: number | null;
  last_stone_loses: boolean;
  turn_timeout: number | null;
}

// GET /matches (history list)
export interface AgentInfo {
  name: string;
  description: string;
}

export interface MatchSummary {
  id: string;
  status: MatchStatus;
  winner_id: string | null;
  created_at: string;
  finished_at: string | null;
  initial_piles: number[];
  max_take: number | null;
  last_stone_loses: boolean;
  player_ids: string[];
  move_count: number;
}

// GET /matches/{id}/replay
export interface Replay {
  id: string;
  status: MatchStatus;
  winner_id: string | null;
  created_at: string;
  finished_at: string | null;
  turn_timeout: number | null;
  initial_piles: number[];
  max_take: number | null;
  last_stone_loses: boolean;
  players: { id: string; name: string; kind: string; seat: number }[];
  moves: (Omit<Move, "piles_after"> & { turn_no: number; piles_after: number[] })[];
}

// Keep in sync with backend/app/game/engine.py
export const MAX_PILES = 10;
export const MAX_STONES_PER_PILE = 30;
