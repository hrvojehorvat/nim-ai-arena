import { matchHash, socketUrl } from "./api";
import { describeRules, renderBoard, seatDot, seatStyle, takeAnimationMs } from "./board";
import { h } from "./dom";
import { metaLine } from "./meta";
import type { Match, ServerMessage } from "./types";

const PERMANENT_CLOSE_CODES = new Set([4403, 4404]);
const RECONNECT_DELAY_MS = 1500;

export function renderMatch(root: HTMLElement, matchId: string, playerId: string | null): () => void {
  let match: Match | null = null;
  let receivedAt = 0; // performance.now() when `match` arrived (for the countdown)
  let ws: WebSocket | null = null;
  let disposed = false;
  let fatal: string | null = null;
  let connection: "connecting" | "open" | "reconnecting" = "connecting";
  let reconnectTimer: number | undefined;
  let toastTimer: number | undefined;
  // Moves already drawn, so only a move that just arrived is animated (not reconnects or re-renders).
  let shownMoves: number | null = null;
  // While the board animates the last move, the banner and players list still show its mover;
  // the next player's "thinking" / "your turn" appears once the stones are gone.
  let takingUntil = 0;
  let takingTimer: number | undefined;

  const toast = h("div", { class: "toast", role: "status" });
  const timerEl = h("span", { class: "timer" });
  const view = h("div");
  root.replaceChildren(view, toast);

  const showToast = (text: string) => {
    toast.textContent = text;
    toast.classList.add("visible");
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3500);
  };

  const name = (id: string) => match?.players.find((p) => p.id === id)?.name ?? id;
  const seatOf = (id: string | null) => match?.players.findIndex((p) => p.id === id) ?? -1;

  const updateTimer = () => {
    if (!match || match.status !== "active" || match.turn_time_left === null) {
      timerEl.textContent = "";
      return;
    }
    const left = Math.max(0, match.turn_time_left - (performance.now() - receivedAt) / 1000);
    timerEl.textContent = `⏱ ${Math.ceil(left)}s`;
    timerEl.classList.toggle("urgent", left <= 5);
  };
  const tick = window.setInterval(updateTimer, 250);

  const sendMove = (pile: number, count: number) => {
    ws?.send(JSON.stringify({ type: "move", pile, count }));
  };

  const render = () => {
    if (fatal) {
      view.replaceChildren(
        h("div", { class: "card" }, h("h2", {}, "Can't open this match"), h("p", {}, fatal), h("a", { href: "#/" }, "← New match")),
      );
      return;
    }
    if (!match) {
      view.replaceChildren(h("p", { class: "muted" }, "Connecting…"));
      return;
    }
    // The view is rebuilt on every update; remember scroll positions so reading isn't interrupted.
    const oldLog = view.querySelector<HTMLElement>(".log");
    const logTop = oldLog?.scrollTop ?? 0;
    const logHeight = oldLog?.scrollHeight ?? 0;
    const pageY = window.scrollY;
    const m = match;
    const myTurn = m.status === "active" && m.current_player_id === playerId;
    const rules = describeRules(m.max_take, m.last_stone_loses);

    const last = m.moves.at(-1);
    const isNew = shownMoves !== null && m.moves.length === shownMoves + 1;
    shownMoves = m.moves.length;
    if (isNew && last) takingUntil = performance.now() + takeAnimationMs();
    const taking = last !== undefined && performance.now() < takingUntil;
    // Any render (new move, toast, reconnect) re-arms the one timer that ends the "taking" phase.
    clearTimeout(takingTimer);
    if (taking) takingTimer = window.setTimeout(render, takingUntil - performance.now() + 30);

    const current = m.players.find((p) => p.id === m.current_player_id);
    const agentThinking = m.status === "active" && current !== undefined && current.kind !== "human";
    // Whose colour the banner and players list show right now.
    const spotlight = taking ? last.player_id : m.status === "active" ? m.current_player_id : null;

    let banner: string;
    let bannerClass = "";
    if (taking) {
      banner = `${name(last.player_id)} takes ${last.count} from Pile ${last.pile + 1}`;
      bannerClass = " seat-tint";
    } else if (m.status === "waiting") {
      const missing = m.players.filter((p) => !p.joined).map((p) => p.name);
      banner = `Waiting for ${missing.join(", ")} to join…`;
    } else if (m.status === "finished") {
      banner = m.winner_id === playerId ? "🏆 You win!" : `🏆 ${name(m.winner_id!)} wins`;
    } else {
      if (myTurn) {
        banner = "Your turn — hover a stone, click to take";
        bannerClass = " my-turn seat-tint";
      } else if (agentThinking) {
        banner = `🤖 ${name(m.current_player_id!)} is thinking`;
        bannerClass = " thinking seat-tint";
      } else {
        banner = `${name(m.current_player_id!)}'s turn`;
        bannerClass = " seat-tint";
      }
    }
    if (m.status === "finished" && !taking) bannerClass = " finished";
    view.replaceChildren(
      h(
        "div",
        { class: "card" },
        h(
          "div",
          { class: "match-header" },
          h("div", {}, h("strong", {}, `Match ${m.id}`), " ", h("span", { class: `badge ${m.status}` }, m.status)),
          h("div", { class: "muted" }, playerId ? `You are ${name(playerId)}` : "Spectating", " · ", rules),
        ),
        h(
          "div",
          { class: `banner${bannerClass}`, style: spotlight ? seatStyle(seatOf(spotlight)) : undefined },
          h("span", { class: "banner-text" }, spotlight ? seatDot(seatOf(spotlight)) : null, banner),
          timerEl,
        ),
        connection === "reconnecting" ? h("p", { class: "form-error" }, "Connection lost — reconnecting…") : null,
        renderBoard({
          piles: m.piles,
          maxTake: m.max_take,
          canMove: myTurn && connection === "open",
          onMove: sendMove,
          seat: myTurn ? seatOf(playerId) : null,
          lastMove: isNew && last ? { pile: last.pile, count: last.count, seat: seatOf(last.player_id) } : null,
        }),
        last
          ? h("p", { class: "muted" }, `Last move: ${name(last.player_id)} took ${last.count} from Pile ${last.pile + 1}${last.auto ? " (timed out — auto move)" : ""}`)
          : null,
        last?.reasoning ? h("p", { class: "why" }, `💭 ${last.reasoning}`) : null,
        metaLine(last?.meta),
      ),
      h(
        "div",
        { class: "side" },
        h(
          "div",
          { class: "card" },
          h("h3", {}, "Players"),
          h(
            "ul",
            { class: "players" },
            ...m.players.map((p, seatIndex) =>
              h(
                "li",
                { class: p.id === spotlight ? "current" : "", style: seatStyle(seatIndex) },
                h("span", {}, seatDot(seatIndex), p.id === spotlight ? "▶ " : "", p.name, p.id === playerId ? " (you)" : ""),
                p.joined
                  ? h("span", { class: "muted" }, "joined")
                  : h("a", { href: matchHash(m.id, p.id), target: "_blank", rel: "noopener" }, "open seat"),
              ),
            ),
          ),
        ),
        h(
          "div",
          { class: "card" },
          h("h3", {}, "Moves"),
          m.moves.length === 0
            ? h("p", { class: "muted" }, "No moves yet.")
            : h(
                "ol",
                { class: "log", reversed: true },
                ...[...m.moves].reverse().map((mv) =>
                  h(
                    "li",
                    {},
                    seatDot(seatOf(mv.player_id)),
                    `${name(mv.player_id)} took ${mv.count} from Pile ${mv.pile + 1} → [${mv.piles_after.join(", ")}]${mv.auto ? " (auto)" : ""}`,
                    mv.reasoning ? h("div", { class: "why" }, mv.reasoning) : null,
                    metaLine(mv.meta),
                  ),
                ),
              ),
          h("p", {}, h("a", { href: "#/" }, "← New match")),
        ),
      ),
    );
    view.className = "match-layout";
    const newLog = view.querySelector<HTMLElement>(".log");
    if (newLog && logTop > 0) {
      // Newest entries are added on top: keep the entries being read in the same place.
      newLog.scrollTop = logTop + (newLog.scrollHeight - logHeight);
    }
    window.scrollTo(0, pageY);
    updateTimer();
  };

  const connect = () => {
    ws = new WebSocket(socketUrl(matchId, playerId));
    ws.addEventListener("open", () => {
      connection = "open";
    });
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data) as ServerMessage;
      if (msg.type === "state") {
        match = msg.match;
        receivedAt = performance.now();
        render();
      } else if (msg.type === "error") {
        if (!match) fatal = msg.message; // rejected on connect; socket closes next
        else showToast(msg.message);
        render();
      }
      // game_over: the final `state` already shows the winner.
    });
    ws.addEventListener("close", (event) => {
      if (disposed) return;
      if (PERMANENT_CLOSE_CODES.has(event.code)) {
        fatal ??= event.reason || "The server rejected this connection.";
      } else if (match?.status !== "finished") {
        connection = "reconnecting";
        reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
      }
      render();
    });
  };

  render();
  connect();

  return () => {
    disposed = true;
    clearInterval(tick);
    clearTimeout(reconnectTimer);
    clearTimeout(toastTimer);
    clearTimeout(takingTimer);
    ws?.close();
  };
}
