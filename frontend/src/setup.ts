import { createMatch, getDefaults, listAgents, matchHash } from "./api";
import { h } from "./dom";
import { MAX_PILES, MAX_STONES_PER_PILE, type AgentInfo, type Match } from "./types";

function parsePiles(raw: string): number[] {
  const parts = raw.split(/[\s,]+/).filter(Boolean);
  if (parts.length < 1 || parts.length > MAX_PILES) {
    throw new Error(`Enter between 1 and ${MAX_PILES} piles.`);
  }
  const piles = parts.map((p) => {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 0 || n > MAX_STONES_PER_PILE) {
      throw new Error(`Each pile must be a whole number from 0 to ${MAX_STONES_PER_PILE}.`);
    }
    return n;
  });
  if (piles.every((n) => n === 0)) throw new Error("At least one pile must have stones.");
  return piles;
}

function optionalNumber(raw: string, label: string, integer: boolean): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0 || (integer && !Number.isInteger(n))) {
    throw new Error(`${label} must be a positive ${integer ? "whole " : ""}number, or empty.`);
  }
  return n;
}

function parseDelay(raw: string): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0 || n > 30) throw new Error("Agent move delay must be 0–30 seconds.");
  return n;
}

// Empty or 0 means "no time limit".
function parseTimeLimit(raw: string): number | null {
  if (raw.trim() === "" || Number(raw) === 0) return null;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0 || n > 3600) {
    throw new Error("Turn time limit must be 1–3600 seconds (empty or 0 = unlimited).");
  }
  return n;
}

function randomPiles(): string {
  const count = 3 + Math.floor(Math.random() * 3);
  return Array.from({ length: count }, () => 1 + Math.floor(Math.random() * 15)).join(", ");
}

export function renderSetup(root: HTMLElement): () => void {
  const pilesInput = h("input", { id: "piles", value: "3, 4, 5", autocomplete: "off" });
  const maxTakeInput = h("input", { id: "max-take", type: "number", min: 1, placeholder: "unlimited" });
  const timeoutInput = h("input", { id: "timeout", type: "number", min: 0, max: 3600, placeholder: "unlimited" });
  const delayInput = h("input", { id: "agent-delay", type: "number", min: 0, max: 30, step: "0.5", placeholder: "default" });
  // An explicit choice (not a checkbox) so the default rule is visible: standard Nim, last stone wins.
  const ruleInput = h(
    "select",
    { id: "rule" },
    h("option", { value: "wins" }, "Last stone wins (standard)"),
    h("option", { value: "loses" }, "Last stone loses (misère)"),
  );
  ruleInput.value = "wins";
  const delayLabel = h(
    "label",
    { for: "agent-delay" },
    "Agent move delay (seconds, empty = server default, 0 = instant)",
  );
  getDefaults()
    .then(({ agent_move_delay: d }) => {
      delayLabel.textContent = `Agent move delay (seconds, empty = server default: ${d}, 0 = instant)`;
      delayInput.placeholder = `default: ${d}`;
    })
    .catch(() => {}); // keep the generic label
  const playersBox = h("div", { class: "players-inputs" });
  const errorBox = h("p", { class: "form-error", role: "alert" });
  const result = h("div", { class: "created" });

  // The agent list comes from the server (GET /agents) and arrives after the first paint.
  let agents: AgentInfo[] = [];
  const fillOptions = (select: HTMLSelectElement) => {
    select.replaceChildren(
      h("option", { value: "human" }, "Human"),
      ...agents.map((a) => h("option", { value: a.name, title: a.description }, `Agent: ${a.name}`)),
    );
    select.value = select.dataset.want ?? "human";
  };

  type Seat = { kind: HTMLSelectElement; input: HTMLInputElement };
  const playerInputs: Seat[] = [];
  const addPlayer = (value: string, kind = "human") => {
    const input = h("input", { value, maxlength: 40, "aria-label": "Player id", autocomplete: "off" });
    const select = h("select", { "aria-label": "Seat type" });
    select.dataset.want = kind; // what the user picked; survives the option list being rebuilt
    select.addEventListener("change", () => (select.dataset.want = select.value));
    fillOptions(select);
    playerInputs.push({ kind: select, input });
    redrawPlayers();
  };
  const redrawPlayers = () => {
    playersBox.replaceChildren(
      ...playerInputs.map(({ kind, input }, i) =>
        h("div", { class: "player-input" }, h("span", { class: "seat" }, `Seat ${i + 1}`), kind, input),
      ),
    );
  };
  // Default match: the deterministic agent vs a local (free) Ollama model, resolved once the list
  // arrives; falls back to the random agent when Ollama isn't running.
  const LOCAL_LLM = "@local-llm";
  const pickLocal = (list: AgentInfo[]) => {
    const names = list.map((a) => a.name);
    const ollama = names.filter((n) => n.startsWith("ollama_"));
    return ollama.find((n) => n === "ollama_qwen2_1_5b") ?? ollama.find((n) => !n.endsWith("_precompute")) ??
      ollama[0] ?? "random";
  };
  addPlayer("agent1", "nim_optimal");
  addPlayer("agent2", LOCAL_LLM);
  let disposed = false;
  listAgents()
    .then((list) => {
      if (disposed) return;
      agents = list;
      playerInputs.forEach(({ kind }) => {
        if (kind.dataset.want === LOCAL_LLM) kind.dataset.want = pickLocal(list);
        fillOptions(kind);
      });
    })
    .catch(() => {
      playerInputs.forEach(({ kind }) => {
        kind.dataset.want = "human";
        fillOptions(kind);
      });
      errorBox.textContent = "Couldn't load the agent list; only human seats are available.";
    });

  const randomBtn = h("button", { type: "button", class: "secondary" }, "Random");
  randomBtn.addEventListener("click", () => (pilesInput.value = randomPiles()));

  const submit = h("button", { type: "submit" }, "Create match");
  const form = h(
    "form",
    { class: "card setup" },
    h("h2", {}, "New match"),
    h("label", { for: "piles" }, `Piles (stones per pile, up to ${MAX_PILES} piles of 0–${MAX_STONES_PER_PILE})`),
    h("div", { class: "row" }, pilesInput, randomBtn),
    h("label", {}, "Players (seat 1 moves first)"),
    playersBox,
    h("div", { class: "row two" },
      h("div", {}, h("label", { for: "max-take" }, "Max stones per move"), maxTakeInput),
      h("div", {}, h("label", { for: "timeout" }, "Turn time limit (seconds, empty = unlimited)"), timeoutInput),
    ),
    delayLabel,
    delayInput,
    h("label", { for: "rule" }, "Winner"),
    ruleInput,
    errorBox,
    submit,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.textContent = "";
    try {
      const players = playerInputs.map((s) => s.input.value.trim());
      if (players.some((p) => p === "")) throw new Error("Player ids cannot be empty.");
      if (new Set(players).size !== players.length) throw new Error("Player ids must be unique.");
      submit.disabled = true;
      const match = await createMatch({
        piles: parsePiles(pilesInput.value),
        players: players.map((id, i) => ({ id, kind: playerInputs[i].kind.value })),
        max_take: optionalNumber(maxTakeInput.value, "Max stones per move", true),
        last_stone_loses: ruleInput.value === "loses",
        turn_timeout: parseTimeLimit(timeoutInput.value),
        agent_move_delay: parseDelay(delayInput.value),
      });
      const humans = match.players.filter((p) => p.kind === "human");
      if (humans.length === 1) {
        // One human vs agents: go straight to that seat, no tab juggling.
        location.hash = matchHash(match.id, humans[0].id);
        return;
      }
      if (humans.length === 0) {
        location.hash = matchHash(match.id, null);
        return;
      }
      result.replaceChildren(renderCreated(match));
    } catch (err) {
      errorBox.textContent = err instanceof Error ? err.message : String(err);
    } finally {
      submit.disabled = false;
    }
  });

  root.replaceChildren(form, result);
  return () => {
    disposed = true;
  };
}

function renderCreated(match: Match): HTMLElement {
  const link = (playerId: string | null, label: string) => {
    const href = matchHash(match.id, playerId);
    const url = new URL(href, location.href).toString();
    const copy = h("button", { type: "button", class: "link" }, "copy link");
    copy.addEventListener("click", async () => {
      await navigator.clipboard?.writeText(url);
      copy.textContent = "copied";
    });
    return h("li", {}, h("a", { href, target: "_blank", rel: "noopener" }, label), " ", copy);
  };
  return h(
    "div",
    { class: "card" },
    h("h2", {}, `Match ${match.id} created`),
    h("p", { class: "muted" }, "Send each human their own link (or open one per tab). The game starts when every human seat has joined."),
    h("ul", { class: "links" },
      ...match.players.filter((p) => p.kind === "human").map((p) => link(p.id, `Play as ${p.id}`)),
      link(null, "Watch as spectator"),
    ),
  );
}
