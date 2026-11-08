import type { CreateMatchRequest, Match } from "./types";

export class ApiError extends Error {}

export async function createMatch(body: CreateMatchRequest): Promise<Match> {
  const res = await fetch("/matches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
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
  return data as Match;
}

export function socketUrl(matchId: string, playerId: string | null): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const query = playerId ? `?player=${encodeURIComponent(playerId)}` : "";
  return `${proto}://${location.host}/ws/matches/${encodeURIComponent(matchId)}${query}`;
}

export function matchHash(matchId: string, playerId: string | null): string {
  return `#/match/${encodeURIComponent(matchId)}` + (playerId ? `/${encodeURIComponent(playerId)}` : "");
}
