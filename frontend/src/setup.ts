import { createMatch, matchHash } from "./api";
import { h } from "./dom";
import { MAX_PILES, MAX_STONES_PER_PILE, type Match } from "./types";

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

// Agent kinds the server knows (see app/main.py).
const AGENT_KINDS = ["nim_optimal", "random"];

export function renderSetup(root: HTMLElement): () => void {
  const pilesInput = h("input", { id: "piles", value: "3, 4, 5", autocomplete: "off" });
  const maxTakeInput = h("input", { id: "max-take", type: "number", min: 1, placeholder: "unlimited" });
  const timeoutInput = h("input", { id: "timeout", type: "number", min: 0, max: 3600, placeholder: "unlimited" });
  const delayInput = h("input", { id: "agent-delay", type: "number", min: 0, max: 30, step: "0.5", placeholder: "default" });
  const lastStoneLosesInput = h("input", { id: "last_stone_loses", type: "checkbox" });
  const playersBox = h("div", { class: "players-inputs" });
  const errorBox = h("p", { class: "form-error", role: "alert" });
  const result = h("div", { class: "created" });

  type Seat = { kind: HTMLSelectElement; input: HTMLInputElement };
  const playerInputs: Seat[] = [];
  const addPlayer = (value: string, kind = "human") => {
    const input = h("input", { value, maxlength: 40, "aria-label": "Player id", autocomplete: "off" });
    const select = h(
      "select",
      { "aria-label": "Seat type" },
      h("option", { value: "human" }, "Human"),
      ...AGENT_KINDS.map((k) => h("option", { value: k }, `Agent: ${k}`)),
    );
    select.value = kind;
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
  addPlayer("you");
  addPlayer("bot", "nim_optimal");

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
    h("label", { for: "agent-delay" }, "Agent move delay (seconds, empty = server default, 0 = instant)"),
    delayInput,
    h("label", { class: "check" }, lastStoneLosesInput, "Last stone loses (the player who takes the last stone is the loser)"),
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
        last_stone_loses: lastStoneLosesInput.checked,
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
  return () => {};
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
