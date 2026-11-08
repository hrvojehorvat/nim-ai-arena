import type { CreateMatchRequest, Match, MatchSummary, Replay } from "./types";

export class ApiError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok) {
    // Our errors are {reason, message}; Pydantic validation errors are {detail: [...]}.
    const message =
      data.message ??
      (Array.isArray(data.detail)
        ? data.detail.map((d: { msg: string }) => d.msg).join("; ")
        : res.statusText);
    throw new ApiError(message);
  }
  return data as T;
}

export const createMatch = (body: CreateMatchRequest) =>
  request<Match>("/matches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

export const listMatches = (limit: number, offset: number) =>
  request<MatchSummary[]>(`/matches?limit=${limit}&offset=${offset}`);

export const getReplay = (matchId: string) =>
  request<Replay>(`/matches/${encodeURIComponent(matchId)}/replay`);

export function socketUrl(matchId: string, playerId: string | null): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const query = playerId ? `?player=${encodeURIComponent(playerId)}` : "";
  return `${proto}://${location.host}/ws/matches/${encodeURIComponent(matchId)}${query}`;
}

export function matchHash(matchId: string, playerId: string | null): string {
  return `#/match/${encodeURIComponent(matchId)}` + (playerId ? `/${encodeURIComponent(playerId)}` : "");
}
