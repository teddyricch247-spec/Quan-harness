import type { SessionEvent } from "./types";

/**
 * One Server-Sent Events frame → a handler call. Pure (no network, no auth), so lib/stream.ts's
 * reader stays thin and this can be exercised on its own.
 *
 * A frame is the text between two blank lines: an optional `event:` line, one or more `data:`
 * lines, and possibly `:` comment lines (the server's heartbeats). A frame with no data, or whose
 * data isn't JSON, is dropped — a malformed frame is never fatal to the stream.
 */
export interface FrameHandlers {
  onEvent: (event: SessionEvent) => void;
  onStatus: (status: string) => void;
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
}
