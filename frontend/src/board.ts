import { GROUP_SIZE, selectionCount } from "./boardGeometry";
import { renderCanvasBoard, type BoardOptions } from "./canvasBoard";
import { h } from "./dom";

export { GROUP_SIZE, selectionCount };

/** One-line description of the rules, e.g. "last stone loses · max 3 per move". */
export function describeRules(maxTake: number | null, lastStoneLoses: boolean): string {
  return [
    lastStoneLoses ? "last stone loses" : "last stone wins",
    maxTake === null ? "take any number per move" : `max ${maxTake} per move`,
  ].join(" · ");
}

/** The canvas board by default; `?board=dom` in the URL switches to the original DOM board. */
export function renderBoard(options: BoardOptions): HTMLElement {
  const useDom = new URLSearchParams(location.search).get("board") === "dom";
  return useDom ? renderDomBoard(options) : renderCanvasBoard(options);
}

/**
 * Renders piles as rows of stones in groups of GROUP_SIZE. Hovering a stone highlights the
 * stones that would be taken (from that stone to the end, capped at maxTake); clicking moves.
 */
export function renderDomBoard({ piles, maxTake, canMove, onMove }: BoardOptions): HTMLElement {
  const board = h("div", { class: `board${canMove ? " can-move" : ""}` });

  piles.forEach((size, pileIndex) => {
    const stones: HTMLButtonElement[] = [];
    const hint = h("span", { class: "pile-hint" });
    const groups = h("div", { class: "stones" });

    const highlight = (count: number) => {
      stones.forEach((s, i) => s.classList.toggle("selected", i >= size - count));
      hint.textContent = count > 0 ? `take ${count}` : "";
    };

    let group: HTMLElement | null = null;
    for (let i = 0; i < size; i++) {
      if (i % GROUP_SIZE === 0) {
        group = h("span", { class: "group" });
        groups.append(group);
      }
      const count = selectionCount(size, i, maxTake);
      const stone = h("button", {
        class: "stone",
        type: "button",
        disabled: !canMove,
        "aria-label": `Pile ${pileIndex + 1}: take ${count}`,
      });
      if (canMove) {
        stone.addEventListener("mouseenter", () => highlight(count));
        stone.addEventListener("focus", () => highlight(count));
        stone.addEventListener("click", () => onMove(pileIndex, count));
      }
      stones.push(stone);
      group!.append(stone);
    }
    if (size === 0) groups.append(h("span", { class: "empty" }, "empty"));
    groups.addEventListener("mouseleave", () => highlight(0));

    board.append(
      h(
        "div",
        { class: `pile${size === 0 ? " is-empty" : ""}` },
        h("span", { class: "pile-label" }, `Pile ${pileIndex + 1}`),
        groups,
        h("span", { class: "pile-count" }, String(size)),
        hint,
      ),
    );
  });

  return board;
}
