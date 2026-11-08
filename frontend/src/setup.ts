import { createMatch, matchHash } from "./api";
import { h } from "./dom";
import { MAX_PILES, MAX_STONES_PER_PILE, type Match } from "./types";

const MAX_PLAYERS = 6;

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

function randomPiles(): string {
  const count = 3 + Math.floor(Math.random() * 3);
  return Array.from({ length: count }, () => 1 + Math.floor(Math.random() * 15)).join(", ");
}

export function renderSetup(root: HTMLElement): () => void {
  const pilesInput = h("input", { id: "piles", value: "3, 4, 5", autocomplete: "off" });
  const maxTakeInput = h("input", { id: "max-take", type: "number", min: 1, placeholder: "unlimited" });
  const timeoutInput = h("input", { id: "timeout", type: "number", min: 1, max: 3600, value: 30, placeholder: "no limit" });
  const playersBox = h("div", { class: "players-inputs" });
  const errorBox = h("p", { class: "form-error", role: "alert" });
  const result = h("div", { class: "created" });

  const playerInputs: HTMLInputElement[] = [];
  const addPlayer = (value: string) => {
    const input = h("input", { value, maxlength: 40, "aria-label": "Player id", autocomplete: "off" });
    playerInputs.push(input);
    redrawPlayers();
  };
  const redrawPlayers = () => {
    playersBox.replaceChildren(
      ...playerInputs.map((input, i) => {
        const remove = h("button", { type: "button", class: "link", disabled: playerInputs.length <= 2 }, "remove");
        remove.addEventListener("click", () => {
          playerInputs.splice(i, 1);
          redrawPlayers();
        });
        return h("div", { class: "player-input" }, h("span", { class: "seat" }, `Seat ${i + 1}`), input, remove);
      }),
    );
    addBtn.disabled = playerInputs.length >= MAX_PLAYERS;
  };
  const addBtn = h("button", { type: "button", class: "secondary" }, "+ Add player");
  addBtn.addEventListener("click", () => addPlayer(`player${playerInputs.length + 1}`));
  addPlayer("alice");
  addPlayer("bob");

  const randomBtn = h("button", { type: "button", class: "secondary" }, "Random");
  randomBtn.addEventListener("click", () => (pilesInput.value = randomPiles()));

  const submit = h("button", { type: "submit" }, "Create match");
  const form = h(
    "form",
    { class: "card setup" },
    h("h2", {}, "New match"),
    h("label", { for: "piles" }, `Piles (stones per pile, up to ${MAX_PILES} piles of 0–${MAX_STONES_PER_PILE})`),
    h("div", { class: "row" }, pilesInput, randomBtn),
    h("label", {}, "Players (turn order)"),
    playersBox,
    addBtn,
    h("div", { class: "row two" },
      h("div", {}, h("label", { for: "max-take" }, "Max stones per move"), maxTakeInput),
      h("div", {}, h("label", { for: "timeout" }, "Turn time limit (seconds)"), timeoutInput),
    ),
    errorBox,
    submit,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.textContent = "";
    try {
      const players = playerInputs.map((i) => i.value.trim());
      if (players.some((p) => p === "")) throw new Error("Player ids cannot be empty.");
      if (new Set(players).size !== players.length) throw new Error("Player ids must be unique.");
      submit.disabled = true;
      const match = await createMatch({
        piles: parsePiles(pilesInput.value),
        players: players.map((id) => ({ id })),
        max_take: optionalNumber(maxTakeInput.value, "Max stones per move", true),
        turn_timeout: optionalNumber(timeoutInput.value, "Turn time limit", false),
      });
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
    h("p", { class: "muted" }, "Open one tab per player (each link takes that seat). The game starts when every seat has joined."),
    h("ul", { class: "links" },
      ...match.players.map((p) => link(p.id, `Play as ${p.id}`)),
      link(null, "Watch as spectator"),
    ),
  );
}
