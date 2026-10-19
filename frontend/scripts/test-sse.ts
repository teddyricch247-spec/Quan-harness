// Run with: npx tsx scripts/test-sse.ts   (from frontend/). Exits non-zero on the first failed check.
import assert from "node:assert/strict";
import { dispatchFrame, type FrameHandlers, type LiveDelta } from "../lib/sse";

function collect() {
  const log: string[] = [];
  const handlers: FrameHandlers = {
    onEvent: (e) => log.push(`event:${e.id}`),
    onStatus: (s) => log.push(`status:${s}`),
    onDelta: (d: LiveDelta) => log.push(`delta:${d.seq}:${d.replace}:${d.text}`),
    onThinking: (d: LiveDelta) => log.push(`thinking:${d.seq}:${d.replace}:${d.text}`),
    onReset: () => log.push("reset"),
  };
  return { log, handlers };
}

// the existing frames still work
{
  const { log, handlers } = collect();
  dispatchFrame('event: event\ndata: {"id": 7}', handlers);
  dispatchFrame('event: status\ndata: {"status": "completed"}', handlers);
  assert.deepEqual(log, ["event:7", "status:completed"]);
}

// a live delta, a reconnect snapshot, and a reset
{
  const { log, handlers } = collect();
  dispatchFrame('event: delta\ndata: {"text": "Hel", "seq": 1}', handlers);
  dispatchFrame('event: delta\ndata: {"text": "Hello wor", "seq": 5, "replace": true}', handlers);
  dispatchFrame("event: reset\ndata: {}", handlers);
  assert.deepEqual(log, ["delta:1:false:Hel", "delta:5:true:Hello wor", "reset"]);
}

// the thinking channel is separate from the reply channel
{
  const { log, handlers } = collect();
  dispatchFrame('event: thinking\ndata: {"text": "hmm", "seq": 1}', handlers);
  dispatchFrame('event: thinking\ndata: {"text": "hmm so far", "seq": 3, "replace": true}', handlers);
  dispatchFrame('event: delta\ndata: {"text": "Hi", "seq": 1}', handlers);
  assert.deepEqual(log, ["thinking:1:false:hmm", "thinking:3:true:hmm so far", "delta:1:false:Hi"]);
}

// text with newlines and a leading space survives (one `data:` line per line is not used by the server, but JSON escapes \n)
{
  const { log, handlers } = collect();
  dispatchFrame('event: delta\ndata: {"text": "a\\n b", "seq": 2}', handlers);
  assert.deepEqual(log, ["delta:2:false:a\n b"]);
}

// a consumer that doesn't show live text can ignore the new frames without handlers
{
  const log: string[] = [];
  const handlers: FrameHandlers = { onEvent: () => log.push("event"), onStatus: () => log.push("status") };
  dispatchFrame('event: delta\ndata: {"text": "x", "seq": 1}', handlers);
  dispatchFrame('event: thinking\ndata: {"text": "x", "seq": 1}', handlers);
  dispatchFrame("event: reset\ndata: {}", handlers);
  assert.deepEqual(log, []);
}

// malformed frames never throw
{
  const { log, handlers } = collect();
  dispatchFrame("event: delta\ndata: not json", handlers);
  dispatchFrame('event: delta\ndata: {"seq": 3}', handlers); // no text
  dispatchFrame(": keep-alive", handlers);
  assert.deepEqual(log, []);
}

console.log("sse frames: all checks passed");
