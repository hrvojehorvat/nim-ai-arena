// Pure board maths for the canvas renderer: where every stone sits, which stone a pointer is on,
// and how the keyboard moves the selection. No DOM here, so it is unit-tested (boardGeometry.test.ts).

export const GROUP_SIZE = 5;

/** How many stones a hover/click on stone `index` selects (stones are taken from the right end). */
export function selectionCount(pileSize: number, index: number, maxTake: number | null): number {
  const wanted = pileSize - index;
  return maxTake === null ? wanted : Math.min(wanted, maxTake);
}

/** The most stones one move may take from a pile of `size`. */
export function maxCount(size: number, maxTake: number | null): number {
  return maxTake === null ? size : Math.min(size, maxTake);
}

export interface Metrics {
  d: number; // stone diameter
  gap: number; // between stones in a group
  groupGap: number; // between groups of 5
  rowGap: number; // between wrapped lines of one pile
  padX: number;
  padY: number;
  labelW: number; // left column: "PILE 1" + count
  hintW: number; // right column: "take 3" pill
  trayGap: number; // between piles
  perLine: number; // stones per line before wrapping (a multiple of GROUP_SIZE)
}

const WIDE: Metrics = {
  d: 24,
  gap: 6,
  groupGap: 18,
  rowGap: 10,
  padX: 18,
  padY: 16,
  labelW: 72,
  hintW: 84,
  trayGap: 10,
  perLine: 10,
};
// Phone-sized: a full line of 10 needs ~316px (a 390px-wide phone leaves ~326px inside the card).
const COMPACT: Metrics = {
  ...WIDE,
  d: 16,
  gap: 4,
  groupGap: 10,
  rowGap: 8,
  padX: 10,
  padY: 12,
  labelW: 38,
  hintW: 56,
};

/** Width of `n` stones on one line, including the wider gaps between groups. */
export function stonesSpan(m: Metrics, n: number): number {
  if (n <= 0) return 0;
  const groups = Math.ceil(n / GROUP_SIZE);
  return n * m.d + (n - groups) * m.gap + (groups - 1) * m.groupGap;
}

function lineWidth(m: Metrics): number {
  return 2 * m.padX + m.labelW + stonesSpan(m, m.perLine) + m.hintW;
}

/** Biggest metrics whose full line (10 stones, or 5 when very narrow) fits in `width`. */
export function chooseMetrics(width: number): Metrics {
  if (lineWidth(WIDE) <= width) return WIDE;
  if (lineWidth(COMPACT) <= width) return COMPACT;
  return { ...COMPACT, perLine: GROUP_SIZE };
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface StoneSpot {
  x: number; // centre
  y: number;
  r: number;
}
export interface PileRow {
  pile: number;
  size: number;
  tray: Rect;
  stones: StoneSpot[];
}
export interface BoardLayout {
  width: number;
  height: number;
  m: Metrics;
  rows: PileRow[];
}

export function layoutBoard(piles: number[], width: number): BoardLayout {
  const m = chooseMetrics(width);
  const rows: PileRow[] = [];
  let y = 0;
  piles.forEach((size, pile) => {
    const lines = Math.max(1, Math.ceil(size / m.perLine));
    const h = 2 * m.padY + lines * m.d + (lines - 1) * m.rowGap;
    const stones: StoneSpot[] = [];
    for (let i = 0; i < size; i++) {
      const line = Math.floor(i / m.perLine);
      const col = i % m.perLine;
      const group = Math.floor(col / GROUP_SIZE);
      stones.push({
        x: m.padX + m.labelW + col * (m.d + m.gap) + group * (m.groupGap - m.gap) + m.d / 2,
        y: y + m.padY + line * (m.d + m.rowGap) + m.d / 2,
        r: m.d / 2,
      });
    }
    rows.push({ pile, size, tray: { x: 0, y, w: width, h }, stones });
    y += h + m.trayGap;
  });
  return { width, height: rows.length ? y - m.trayGap : 0, m, rows };
}

export interface Hit {
  pile: number;
  index: number;
}

/** The stone under (x, y), forgiving: anywhere in a tray snaps to the nearest stone if close. */
export function hitTest(layout: BoardLayout, x: number, y: number): Hit | null {
  const row = layout.rows.find((r) => y >= r.tray.y && y < r.tray.y + r.tray.h && x >= 0 && x < r.tray.w);
  if (!row || row.size === 0) return null;
  let best = -1;
  let bestDist = Infinity;
  row.stones.forEach((s, i) => {
    const dist = Math.hypot(s.x - x, s.y - y);
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  });
  return bestDist <= layout.m.d * 0.85 ? { pile: row.pile, index: best } : null;
}

export interface Selection {
  pile: number;
  count: number;
}

/**
 * Keyboard control. Up/Down: previous/next non-empty pile. Left: take one more (the highlight grows
 * to the left, like the stones), Right: one fewer. 1-9: take that many. Enter/Space: play it.
 * Returns the new selection, `move: true` to play it, or null when the key isn't ours.
 */
export function applyKey(
  sel: Selection | null,
  key: string,
  piles: number[],
  maxTake: number | null,
): { sel: Selection | null; move: boolean } | null {
  const playable = piles.map((s, i) => (s > 0 ? i : -1)).filter((i) => i >= 0);
  if (playable.length === 0) return null;
  const clamp = (pile: number, count: number) => ({
    pile,
    count: Math.max(1, Math.min(count, maxCount(piles[pile], maxTake))),
  });
  const current = sel ?? clamp(playable[0], 1);
  const step = (dir: number) => {
    const at = playable.indexOf(current.pile);
    const next = playable[(at + dir + playable.length) % playable.length];
    return clamp(next, current.count);
  };
  switch (key) {
    case "ArrowDown":
      return { sel: sel ? step(1) : current, move: false };
    case "ArrowUp":
      return { sel: sel ? step(-1) : current, move: false };
    case "ArrowLeft":
    case "+":
      return { sel: sel ? clamp(current.pile, current.count + 1) : current, move: false };
    case "ArrowRight":
    case "-":
      return { sel: clamp(current.pile, current.count - 1), move: false };
    case "Enter":
    case " ":
      return sel ? { sel, move: true } : { sel: current, move: false };
    case "Escape":
      return { sel: null, move: false };
    default:
      if (/^[1-9]$/.test(key)) return { sel: clamp(current.pile, Number(key)), move: false };
      return null;
  }
}

// --- taking animation (6.2) -----------------------------------------------------------------

/** Total length of the "stones being taken" animation. */
export const TAKE_MS = 1400;
const LIGHT_END = 0.22; // stones light up in the mover's colour and lift
const HOLD_END = 0.38; // ... stay there for a moment, so it is clear which stones go
const STAGGER = 0.06; // then float away one after another (rightmost first)

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const easeOut = (v: number) => 1 - (1 - v) ** 3;
const easeInOut = (v: number) => (v < 0.5 ? 4 * v ** 3 : 1 - (-2 * v + 2) ** 3 / 2);

export interface TakeFrame {
  lift: number; // 0..1: highlight colour + small lift (like a hover selection)
  rise: number; // 0..1: how far it has floated up and away
  alpha: number;
  scale: number;
}

/**
 * Where taken stone `k` (0 = leftmost) of `n` is at progress `t` (0..1) of the take animation.
 * At t = 0 it looks like a resting stone; by t = 1 every stone is gone (alpha 0).
 */
export function takeFrame(t: number, k: number, n: number): TakeFrame {
  const lift = easeOut(clamp01(t / LIGHT_END));
  const spread = Math.min(0.25, STAGGER * (n - 1));
  const order = n > 1 ? (n - 1 - k) / (n - 1) : 0; // rightmost stone leaves first
  const start = HOLD_END + spread * order;
  const u = easeInOut(clamp01((t - start) / (1 - HOLD_END - spread)));
  return { lift, rise: u, alpha: t >= 1 ? 0 : 1 - u, scale: 1 - 0.3 * u };
}
