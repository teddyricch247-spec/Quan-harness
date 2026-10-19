import type { SessionEvent } from "./types";

/**
 * One Server-Sent Events frame → a handler call. Pure (no network, no auth), so lib/stream.ts's
 * reader stays thin and this can be exercised on its own.
 *
 * A frame is the text between two blank lines: an optional `event:` line, one or more `data:`
 * lines, and possibly `:` comment lines (the server's heartbeats). A frame with no data, or whose
 * data isn't JSON, is dropped — a malformed frame is never fatal to the stream.
 *
 * Three frames exist only while the agent is working and are never stored: `delta` (more of the reply so far), `thinking`
 * (more of its thinking so far) and `reset` (discard both). Handlers for them are optional, so a consumer that doesn't
 * show live text simply ignores them.
 */
export interface LiveDelta {
  text: string;
  /** Counts up from 1 within one reply; lets a reconnecting viewer ignore text it already has. */
  seq: number;
  /** True on the first frame after (re)connecting: `text` is the whole thing so far, not a continuation. */
  replace: boolean;
}

export interface FrameHandlers {
  onEvent: (event: SessionEvent) => void;
  onStatus: (status: string) => void;
  onDelta?: (delta: LiveDelta) => void;
  /** The model's thinking so far — the same shape as a reply delta, on its own channel. */
  onThinking?: (delta: LiveDelta) => void;
  onReset?: () => void;
}

export function dispatchFrame(frame: string, handlers: FrameHandlers): void {
  let name = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (data.length === 0) return;
  let payload: unknown;
  try {
    payload = JSON.parse(data.join("\n"));
  } catch {
    return;
  }
  if (name === "event") handlers.onEvent(payload as SessionEvent);
  else if (name === "status") handlers.onStatus((payload as { status: string }).status);
  else if (name === "delta" || name === "thinking") {
    const d = payload as Partial<LiveDelta>;
    const handler = name === "delta" ? handlers.onDelta : handlers.onThinking;
    if (typeof d.text === "string") handler?.({ text: d.text, seq: Number(d.seq) || 0, replace: Boolean(d.replace) });
  } else if (name === "reset") handlers.onReset?.();
}
