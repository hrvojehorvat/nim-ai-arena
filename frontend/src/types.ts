// Mirrors backend/app/schemas.py (MatchOut) and backend/app/ws.py (protocol).

export type MatchStatus = "waiting" | "active" | "finished";

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
}

export interface Match {
  id: string;
  status: MatchStatus;
  max_take: number | null;
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
  players: { id: string }[];
  max_take: number | null;
  turn_timeout: number | null;
}

// Keep in sync with backend/app/game/engine.py
export const MAX_PILES = 10;
export const MAX_STONES_PER_PILE = 30;
