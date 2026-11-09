import { describe, expect, it } from "vitest";
import {
  applyKey,
  chooseMetrics,
  hitTest,
  layoutBoard,
  maxCount,
  selectionCount,
  stonesSpan,
} from "./boardGeometry";

describe("selectionCount / maxCount", () => {
  it("takes from the hovered stone to the end", () => {
    expect(selectionCount(7, 0, null)).toBe(7);
    expect(selectionCount(7, 5, null)).toBe(2);
  });
  it("is capped by maxTake", () => {
    expect(selectionCount(7, 0, 3)).toBe(3);
    expect(maxCount(7, 3)).toBe(3);
    expect(maxCount(2, 3)).toBe(2);
    expect(maxCount(9, null)).toBe(9);
  });
});

describe("chooseMetrics", () => {
  it("uses big stones on wide screens, smaller ones on narrow, 5 per line when tiny", () => {
    const wide = chooseMetrics(800);
    const compact = chooseMetrics(330);
    const tiny = chooseMetrics(240);
    expect(wide.perLine).toBe(10);
    expect(compact.d).toBeLessThan(wide.d);
    expect(compact.perLine).toBe(10);
    expect(tiny.perLine).toBe(5);
  });
  it("adds the group gap between groups of 5", () => {
    const m = chooseMetrics(800);
    expect(stonesSpan(m, 5)).toBe(5 * m.d + 4 * m.gap);
    expect(stonesSpan(m, 10)).toBe(10 * m.d + 8 * m.gap + m.groupGap);
    expect(stonesSpan(m, 0)).toBe(0);
  });
});

describe("layoutBoard", () => {
  it("places one stone per spot and stacks trays", () => {
    const l = layoutBoard([3, 0, 12], 800);
    expect(l.rows.map((r) => r.stones.length)).toEqual([3, 0, 12]);
    expect(l.rows[1].tray.y).toBe(l.rows[0].tray.y + l.rows[0].tray.h + l.m.trayGap);
    expect(l.height).toBe(l.rows[2].tray.y + l.rows[2].tray.h);
  });
  it("wraps after perLine stones and leaves a wider gap between groups", () => {
    const l = layoutBoard([12], 800);
    const s = l.rows[0].stones;
    expect(s[10].y).toBeGreaterThan(s[0].y); // stone 11 starts line 2
    expect(s[10].x).toBe(s[0].x);
    expect(s[5].x - s[4].x).toBe(l.m.d + l.m.groupGap);
    expect(s[1].x - s[0].x).toBe(l.m.d + l.m.gap);
  });
  it("keeps every stone inside its tray", () => {
    for (const width of [240, 380, 800]) {
      const l = layoutBoard([30, 7], width);
      for (const row of l.rows) {
        for (const s of row.stones) {
          expect(s.x + s.r).toBeLessThanOrEqual(row.tray.w);
          expect(s.y - s.r).toBeGreaterThanOrEqual(row.tray.y);
          expect(s.y + s.r).toBeLessThanOrEqual(row.tray.y + row.tray.h);
        }
      }
    }
  });
});

describe("hitTest", () => {
  const l = layoutBoard([4, 0, 6], 800);
  it("finds the stone under the pointer", () => {
    const s = l.rows[2].stones[3];
    expect(hitTest(l, s.x, s.y)).toEqual({ pile: 2, index: 3 });
    expect(hitTest(l, s.x + l.m.d * 0.4, s.y)).toEqual({ pile: 2, index: 3 });
  });
  it("ignores empty piles, label area, gaps between trays and the far right", () => {
    const empty = l.rows[1].tray;
    expect(hitTest(l, 200, empty.y + empty.h / 2)).toBeNull();
    expect(hitTest(l, 10, l.rows[0].stones[0].y)).toBeNull();
    expect(hitTest(l, 200, l.rows[0].tray.h + l.m.trayGap / 2)).toBeNull();
    expect(hitTest(l, 790, l.rows[0].stones[0].y)).toBeNull();
  });
});

describe("applyKey", () => {
  const piles = [3, 0, 5];
  it("selects the first playable pile on the first key", () => {
    expect(applyKey(null, "ArrowDown", piles, null)).toEqual({ sel: { pile: 0, count: 1 }, move: false });
    expect(applyKey(null, "Enter", piles, null)).toEqual({ sel: { pile: 0, count: 1 }, move: false });
  });
  it("skips empty piles and wraps around", () => {
    expect(applyKey({ pile: 0, count: 1 }, "ArrowDown", piles, null)?.sel).toEqual({ pile: 2, count: 1 });
    expect(applyKey({ pile: 2, count: 1 }, "ArrowDown", piles, null)?.sel).toEqual({ pile: 0, count: 1 });
    expect(applyKey({ pile: 0, count: 1 }, "ArrowUp", piles, null)?.sel).toEqual({ pile: 2, count: 1 });
  });
  it("changes the count within 1..min(pile, maxTake)", () => {
    expect(applyKey({ pile: 2, count: 1 }, "ArrowLeft", piles, null)?.sel).toEqual({ pile: 2, count: 2 });
    expect(applyKey({ pile: 2, count: 2 }, "ArrowLeft", piles, 2)?.sel).toEqual({ pile: 2, count: 2 });
    expect(applyKey({ pile: 2, count: 1 }, "ArrowRight", piles, null)?.sel).toEqual({ pile: 2, count: 1 });
    expect(applyKey({ pile: 2, count: 1 }, "9", piles, null)?.sel).toEqual({ pile: 2, count: 5 });
  });
  it("clamps the count when moving to a smaller pile", () => {
    expect(applyKey({ pile: 2, count: 5 }, "ArrowDown", piles, null)?.sel).toEqual({ pile: 0, count: 3 });
  });
  it("plays on Enter / Space, clears on Escape, ignores other keys", () => {
    expect(applyKey({ pile: 2, count: 4 }, "Enter", piles, null)).toEqual({ sel: { pile: 2, count: 4 }, move: true });
    expect(applyKey({ pile: 2, count: 4 }, " ", piles, null)?.move).toBe(true);
    expect(applyKey({ pile: 2, count: 4 }, "Escape", piles, null)).toEqual({ sel: null, move: false });
    expect(applyKey(null, "a", piles, null)).toBeNull();
    expect(applyKey(null, "Enter", [0, 0], null)).toBeNull();
  });
});
