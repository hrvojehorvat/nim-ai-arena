import { getReplay, listMatches } from "./api";
import { describeRules, renderBoard } from "./board";
import { h } from "./dom";
import { metaLine } from "./meta";
import type { MatchSummary, Replay } from "./types";

const PAGE_SIZE = 20;

const when = (iso: string) => new Date(iso).toLocaleString();
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** "#/history": saved matches, newest first, with a Replay link each. */
export function renderHistory(root: HTMLElement): () => void {
  let disposed = false;
  let offset = 0;
  const view = h("div", { class: "card" });
  root.replaceChildren(view);

  const load = async () => {
    view.replaceChildren(h("p", { class: "muted" }, "Loading…"));
    let rows: MatchSummary[];
    try {
      rows = await listMatches(PAGE_SIZE, offset);
    } catch (e) {
      if (!disposed) view.replaceChildren(h("h2", {}, "History"), h("p", { class: "form-error" }, errorText(e)));
      return;
    }
    if (disposed) return;
    const table =
      rows.length === 0
        ? h("p", { class: "muted" }, "No saved matches.")
        : h(
            "table",
            { class: "history" },
            h("thead", {}, h("tr", {}, ...["Started", "Players", "Piles", "Moves", "Result", ""].map((t) => h("th", {}, t)))),
            h(
              "tbody",
              {},
              ...rows.map((r) =>
                h(
                  "tr",
                  {},
                  h("td", {}, when(r.created_at)),
                  h("td", {}, r.player_ids.join(" vs ")),
                  h("td", {}, `[${r.initial_piles.join(", ")}]` + (r.max_take ? ` max ${r.max_take}` : "") + (r.last_stone_loses ? " last stone loses" : "")),
                  h("td", {}, String(r.move_count)),
                  h("td", {}, r.winner_id ? `🏆 ${r.winner_id}` : h("span", { class: `badge ${r.status}` }, r.status)),
                  h("td", {}, h("a", { href: `#/replay/${encodeURIComponent(r.id)}` }, "Replay")),
                ),
              ),
            ),
          );
    const prev = h("button", { class: "secondary", type: "button", disabled: offset === 0 }, "← Newer");
    const next = h("button", { class: "secondary", type: "button", disabled: rows.length < PAGE_SIZE }, "Older →");
    prev.addEventListener("click", () => { offset = Math.max(0, offset - PAGE_SIZE); void load(); });
    next.addEventListener("click", () => { offset += PAGE_SIZE; void load(); });
    view.replaceChildren(h("h2", {}, "History"), h("div", { class: "table-wrap" }, table), h("div", { class: "row pager" }, prev, next));
  };
  void load();
  return () => { disposed = true; };
}

/** "#/replay/<id>": step through a saved match with buttons or ←/→ keys. */
export function renderReplay(root: HTMLElement, matchId: string): () => void {
  let disposed = false;
  let replay: Replay | null = null;
  let step = 0; // number of moves applied; 0 = initial position
  let error: string | null = null;
  const view = h("div");
  root.replaceChildren(view);

  const name = (id: string) => replay?.players.find((p) => p.id === id)?.name ?? id;

  const go = (to: number) => {
    if (!replay) return;
    step = Math.min(replay.moves.length, Math.max(0, to));
    render();
  };

  const render = () => {
    if (error) {
      view.replaceChildren(h("div", { class: "card" }, h("h2", {}, "Can't open this replay"), h("p", {}, error), h("a", { href: "#/history" }, "← History")));
      view.className = "";
      return;
    }
    if (!replay) {
      view.replaceChildren(h("p", { class: "muted" }, "Loading…"));
      return;
    }
    const r = replay;
    const total = r.moves.length;
    const piles = step === 0 ? r.initial_piles : r.moves[step - 1].piles_after;
    const mv = step > 0 ? r.moves[step - 1] : null;
    const rules = describeRules(r.max_take, r.last_stone_loses);
    let result = r.status === "finished" ? `🏆 ${name(r.winner_id!)} wins` : `Match ${r.status}`;
    if (step < total) result = "";

    const btn = (label: string, title: string, to: number, disabled: boolean) => {
      const b = h("button", { class: "secondary", type: "button", title, disabled }, label);
      b.addEventListener("click", () => go(to));
      return b;
    };

    view.className = "match-layout";
    view.replaceChildren(
      h(
        "div",
        { class: "card" },
        h(
          "div",
          { class: "match-header" },
          h("div", {}, h("strong", {}, `Replay ${r.id}`), " ", h("span", { class: `badge ${r.status}` }, r.status)),
          h("div", { class: "muted" }, r.players.map((p) => p.name).join(" vs "), " · ", rules),
        ),
        h(
          "div",
          { class: "banner" },
          h("span", {}, mv ? `Move ${step}: ${name(mv.player_id)} took ${mv.count} from Pile ${mv.pile + 1}${mv.auto ? " (auto)" : ""}` : "Initial position"),
          h("span", {}, result),
        ),
        renderBoard({ piles, maxTake: r.max_take, canMove: false, onMove: () => {} }),
        mv?.reasoning ? h("p", { class: "why" }, `💭 ${mv.reasoning}`) : null,
        metaLine(mv?.meta),
        h(
          "div",
          { class: "row controls" },
          btn("⏮", "Start", 0, step === 0),
          btn("◀", "Back (←)", step - 1, step === 0),
          h("span", { class: "muted step" }, `${step} / ${total}`),
          btn("▶", "Forward (→)", step + 1, step === total),
          btn("⏭", "End", total, step === total),
        ),
      ),
      h(
        "div",
        { class: "side" },
        h(
          "div",
          { class: "card" },
          h("h3", {}, "Moves"),
          total === 0
            ? h("p", { class: "muted" }, "No moves were played.")
            : h(
                "ol",
                { class: "log clickable" },
                ...r.moves.map((m, i) => {
                  const li = h(
                    "li",
                    { class: i + 1 === step ? "current" : "" },
                    `${name(m.player_id)} took ${m.count} from Pile ${m.pile + 1} → [${m.piles_after.join(", ")}]${m.auto ? " (auto)" : ""}`,
                    m.reasoning ? h("div", { class: "why" }, m.reasoning) : null,
                    metaLine(m.meta),
                  );
                  li.addEventListener("click", () => go(i + 1));
                  return li;
                }),
              ),
          h("p", {}, h("a", { href: "#/history" }, "← History")),
        ),
      ),
    );
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft") go(step - 1);
    else if (e.key === "ArrowRight") go(step + 1);
  };
  window.addEventListener("keydown", onKey);

  render();
  getReplay(matchId).then(
    (data) => { if (!disposed) { replay = data; render(); } },
    (e) => { if (!disposed) { error = errorText(e); render(); } },
  );

  return () => {
    disposed = true;
    window.removeEventListener("keydown", onKey);
  };
}
