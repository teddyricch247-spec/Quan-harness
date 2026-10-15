"use client";

import { apiUrl, authHeaders } from "./api";
import { dispatchFrame } from "./sse";
import type { SessionEvent } from "./types";

/**
 * A fetch()-based Server-Sent Events reader for `GET /sessions/{id}/stream`.
 *
 * Why not EventSource: the browser's EventSource cannot send an Authorization header, and every
 * endpoint here authenticates with a Bearer token (see lib/api.ts). the old DeployPanel's comment
 * named this as the open problem for the agent stream; this is the "fetch()-based streaming reader"
 * it pointed to.
 *
 * Behavior mirrors routers/agent.py's stream_session: a catch-up burst of every event after
 * `afterId`, then live events, `status` frames, and heartbeat comments. The server ends the stream
 * itself on a terminal status (completed / failed / stuck / waiting_approval); `onClose` fires then,
 * and the caller reconnects with the last event id it saw to watch a later turn — the same path a
 * dropped connection uses.
 */
export interface SessionStreamHandlers {
  onEvent: (event: SessionEvent) => void;
  onStatus: (status: string) => void;
  onClose: (reason: "ended" | "aborted" | "error", error?: Error) => void;
}

export function openSessionStream(sessionId: string, afterId: number | null, handlers: SessionStreamHandlers): () => void {
  const controller = new AbortController();

  (async () => {
    try {
      const query = afterId != null ? `?after_id=${afterId}` : "";
      const res = await fetch(apiUrl(`/sessions/${sessionId}/stream${query}`), {
        headers: { Accept: "text/event-stream", ...(await authHeaders()) },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`Could not open the session stream (${res.status}).`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let split: number;
        while ((split = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          dispatchFrame(frame, handlers);
        }
      }
      handlers.onClose("ended");
    } catch (e) {
      if (controller.signal.aborted) handlers.onClose("aborted");
      else handlers.onClose("error", e as Error);
    }
  })();

  return () => controller.abort();
}
