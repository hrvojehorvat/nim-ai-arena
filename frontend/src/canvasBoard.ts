// Canvas board: same contract as the DOM board (renderBoard in board.ts), drawn on an HTML5 canvas.
// Layout / hit-testing / keyboard maths live in boardGeometry.ts; this file only draws and wires input.

import {
  applyKey,
  hitTest,
  layoutBoard,
  maxCount,
  selectionCount,
  type BoardLayout,
  type Selection,
} from "./boardGeometry";
import { h } from "./dom";

export interface BoardOptions {
  piles: number[];
  maxTake: number | null;
  canMove: boolean;
  onMove: (pile: number, count: number) => void;
}

const LIFT_PX = 3;
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const darkScheme = window.matchMedia("(prefers-color-scheme: dark)");

// The match view is rebuilt after every server update, so a keyboard player would lose focus after
// each move. When the last move came from the keyboard, the next playable board takes focus again.
let restoreFocus = false;

interface Palette {
  bg: string;
  card: string;
  text: string;
  muted: string;
  border: string;
  accent: string;
  stone: string;
  stoneHi: string;
  font: string;
}

function readPalette(el: Element): Palette {
  const css = getComputedStyle(el);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    bg: v("--bg"),
    card: v("--card"),
    text: v("--text"),
    muted: v("--muted"),
    border: v("--border"),
    accent: v("--accent"),
    stone: v("--stone"),
    stoneHi: v("--stone-hi"),
    font: css.fontFamily || "system-ui, sans-serif",
  };
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function drawStone(
  ctx: CanvasRenderingContext2D,
  p: Palette,
  x: number,
  y: number,
  r: number,
  lift: number, // 0 = resting, 1 = selected
) {
  const cy = y - LIFT_PX * lift;
  const rr = r * (1 + 0.06 * lift);

  // Soft contact shadow on the tray: wider and fainter as the stone lifts.
  ctx.save();
  ctx.globalAlpha = 0.18 - 0.06 * lift;
  ctx.fillStyle = "#000";
  ctx.beginPath();
  ctx.ellipse(x, y + r * 0.82, r * (0.8 + 0.15 * lift), r * 0.22, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();

  // Body: base colour, cross-faded to the highlight colour, with a glow while selected.
  ctx.save();
  if (lift > 0.01) {
    ctx.shadowColor = p.stoneHi;
    ctx.shadowBlur = 12 * lift;
  }
  ctx.fillStyle = p.stone;
  ctx.beginPath();
  ctx.arc(x, cy, rr, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  if (lift > 0.01) {
    ctx.save();
    ctx.globalAlpha = Math.min(1, lift);
    ctx.fillStyle = p.stoneHi;
    ctx.beginPath();
    ctx.arc(x, cy, rr, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  // Shading: darker rim, then a glossy highlight up and to the left. Works for any base colour.
  const rim = ctx.createRadialGradient(x, cy, rr * 0.35, x, cy, rr);
  rim.addColorStop(0, "rgba(0,0,0,0)");
  rim.addColorStop(1, "rgba(0,0,0,0.28)");
  ctx.fillStyle = rim;
  ctx.beginPath();
  ctx.arc(x, cy, rr, 0, Math.PI * 2);
  ctx.fill();

  const gloss = ctx.createRadialGradient(x - rr * 0.35, cy - rr * 0.45, 0, x - rr * 0.35, cy - rr * 0.45, rr * 0.75);
  gloss.addColorStop(0, "rgba(255,255,255,0.55)");
  gloss.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gloss;
  ctx.beginPath();
  ctx.arc(x, cy, rr, 0, Math.PI * 2);
  ctx.fill();
}

export function renderCanvasBoard({ piles, maxTake, canMove, onMove }: BoardOptions): HTMLElement {
  const canvas = h("canvas", { class: "board-canvas" }) as HTMLCanvasElement;
  const live = h("span", { class: "sr-only", "aria-live": "polite" });
  const wrap = h("div", { class: `canvas-board${canMove ? " can-move" : ""}` }, canvas, live);

  const summary = piles.map((s, i) => `pile ${i + 1}: ${s}`).join(", ");
  if (canMove) {
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "application");
    canvas.setAttribute(
      "aria-label",
      `Nim board, ${summary}. Up and down arrows pick a pile, left and right change how many, ` +
        `number keys set the count, Enter plays.`,
    );
  } else {
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `Nim board, ${summary}.`);
  }

  const ctx = canvas.getContext("2d")!;
  let layout: BoardLayout = layoutBoard(piles, 560);
  let palette: Palette | null = null;
  let sel: Selection | null = null;
  let tapped: Selection | null = null; // touch: first tap selects, second tap on the same one plays
  const lift = piles.map((size) => new Array<number>(size).fill(0));
  let frame = 0;

  const isSelected = (pile: number, i: number) =>
    sel !== null && sel.pile === pile && i >= piles[pile] - sel.count;

  function draw() {
    // Not on the page yet: CSS variables can't be read. The ResizeObserver draws once attached.
    if (!wrap.isConnected) return;
    if (!palette) palette = readPalette(wrap);
    const p = palette;
    const dpr = window.devicePixelRatio || 1;
    const { width, height } = layout;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.height = `${height}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const m = layout.m;
    const small = m.d < 20; // phone metrics: tighter type to fit the narrower columns

    for (const row of layout.rows) {
      const { tray } = row;
      const active = sel?.pile === row.pile;

      // Tray
      roundRect(ctx, tray.x + 0.5, tray.y + 0.5, tray.w - 1, tray.h - 1, 12);
      ctx.fillStyle = p.bg;
      ctx.fill();
      if (active) {
        ctx.save();
        ctx.globalAlpha = 0.08;
        ctx.fillStyle = p.stoneHi;
        ctx.fill();
        ctx.restore();
      }
      ctx.lineWidth = 1;
      ctx.strokeStyle = active ? p.stoneHi : p.border;
      ctx.stroke();

      // Label column: "PILE 1" over the stone count.
      const midY = tray.y + tray.h / 2;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      ctx.fillStyle = p.muted;
      ctx.font = `600 ${small ? 9 : 10}px ${p.font}`;
      ctx.letterSpacing = small ? "0.03em" : "0.08em";
      ctx.fillText(`PILE ${row.pile + 1}`, m.padX, midY - 9);
      ctx.letterSpacing = "0px";
      ctx.fillStyle = row.size === 0 ? p.muted : p.text;
      ctx.font = `700 ${small ? 15 : 18}px ${p.font}`;
      ctx.fillText(String(row.size), m.padX, midY + 8);

      // Stones (or an "empty" note).
      if (row.size === 0) {
        ctx.fillStyle = p.muted;
        ctx.font = `italic 13px ${p.font}`;
        ctx.fillText("empty", m.padX + m.labelW, midY);
      }
      row.stones.forEach((s, i) => drawStone(ctx, p, s.x, s.y, s.r, lift[row.pile][i]));

      // "take N" pill on the right of the selected pile.
      if (active && sel) {
        const label = `take ${sel.count}`;
        ctx.font = `700 ${small ? 11 : 12}px ${p.font}`;
        const pw = ctx.measureText(label).width + (small ? 14 : 20);
        const ph = small ? 20 : 24;
        const px = tray.w - m.padX - pw;
        roundRect(ctx, px, midY - ph / 2, pw, ph, ph / 2);
        ctx.fillStyle = p.stoneHi;
        ctx.fill();
        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.fillText(label, px + pw / 2, midY + 0.5);
      }
    }
  }

  // Ease every stone toward its target lift; one rAF loop runs while anything is still moving.
  function animate() {
    cancelAnimationFrame(frame);
    const instant = reducedMotion();
    const tick = () => {
      let moving = false;
      lift.forEach((stones, pile) =>
        stones.forEach((v, i) => {
          const target = isSelected(pile, i) ? 1 : 0;
          const next = instant ? target : v + (target - v) * 0.3;
          stones[i] = Math.abs(target - next) < 0.01 ? target : next;
          if (stones[i] !== target) moving = true;
        }),
      );
      draw();
      if (moving) frame = requestAnimationFrame(tick);
    };
    tick();
  }

  function select(next: Selection | null, announce = false) {
    const same = next?.pile === sel?.pile && next?.count === sel?.count;
    sel = next;
    if (!same) animate();
    if (announce) {
      live.textContent = sel
        ? `Pile ${sel.pile + 1}, ${piles[sel.pile]} stones: take ${sel.count}. Enter to play.`
        : "Selection cleared.";
    }
  }

  function play(s: Selection) {
    if (s.count < 1 || s.count > maxCount(piles[s.pile], maxTake)) return;
    onMove(s.pile, s.count);
  }

  function relayout() {
    const width = Math.floor(wrap.clientWidth);
    if (width > 0 && width !== layout.width) layout = layoutBoard(piles, width);
    draw();
  }

  // Redraw on resize and on light/dark switch. Both stop once the board leaves the page
  // (the match view throws the whole board away on every update).
  const resize = new ResizeObserver(() => {
    if (!wrap.isConnected) return resize.disconnect();
    relayout();
    if (canMove && restoreFocus && document.activeElement !== canvas) {
      restoreFocus = false;
      canvas.focus({ preventScroll: true });
    }
  });
  resize.observe(wrap);
  const onTheme = () => {
    if (!wrap.isConnected) return darkScheme.removeEventListener("change", onTheme);
    palette = null;
    draw();
  };
  darkScheme.addEventListener("change", onTheme);

  if (canMove) {
    const pointAt = (e: PointerEvent): Selection | null => {
      const r = canvas.getBoundingClientRect();
      const hit = hitTest(layout, e.clientX - r.left, e.clientY - r.top);
      return hit ? { pile: hit.pile, count: selectionCount(piles[hit.pile], hit.index, maxTake) } : null;
    };
    canvas.addEventListener("pointermove", (e) => {
      if (e.pointerType !== "mouse") return;
      const at = pointAt(e);
      canvas.style.cursor = at ? "pointer" : "default";
      if (at) select(at);
    });
    canvas.addEventListener("pointerleave", (e) => {
      if (e.pointerType === "mouse") select(null);
    });
    canvas.addEventListener("pointerup", (e) => {
      const at = pointAt(e);
      if (!at) return;
      if (e.pointerType === "mouse") return play(at);
      if (tapped && tapped.pile === at.pile && tapped.count === at.count) return play(at);
      tapped = at;
      select(at, true);
    });
    canvas.addEventListener("keydown", (e) => {
      const result = applyKey(sel, e.key, piles, maxTake);
      if (!result) return;
      e.preventDefault();
      if (result.move && result.sel) {
        restoreFocus = true;
        return play(result.sel);
      }
      select(result.sel, true);
    });
    canvas.addEventListener("blur", () => {
      if (!canvas.matches(":hover")) select(null);
    });
  }

  draw();
  return wrap;
}
