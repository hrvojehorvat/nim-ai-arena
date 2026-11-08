import { h } from "./dom";
import type { MoveMeta } from "./types";

/** One muted line about how an agent produced a move, e.g. "🛠 gpt-oss · 2 calls · 1 tool call". */
export function metaLine(meta: MoveMeta | null | undefined): HTMLElement | null {
  if (!meta) return null;
  const parts = [
    meta.model,
    meta.mode,
    `${meta.seconds}s`,
    `${meta.calls} call${meta.calls === 1 ? "" : "s"}`,
  ];
  if (meta.tool_calls) parts.push(`${meta.tool_calls} tool call${meta.tool_calls === 1 ? "" : "s"}`);
  if (meta.retries) parts.push(`${meta.retries} retr${meta.retries === 1 ? "y" : "ies"}`);
  if (meta.tokens_in || meta.tokens_out) parts.push(`${meta.tokens_in}→${meta.tokens_out} tokens`);
  if (meta.fell_back) parts.push("⚠ fell back to a safe move");
  return h("div", { class: "why meta" }, `🛠 ${parts.join(" · ")}`);
}
