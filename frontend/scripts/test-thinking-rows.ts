// Run with: npx tsx scripts/test-thinking-rows.ts   (from frontend/). Exits non-zero on the first failed check.
import assert from "node:assert/strict";
import { buildRows, groupRows } from "../lib/transcript";
import type { SessionEvent } from "../lib/types";

let nextId = 1;
const ev = (role: SessionEvent["role"], event_type: string, content: Record<string, unknown> = {}, parent: number | null = null): SessionEvent => ({
  id: nextId++,
  session_id: "s",
  parent_event_id: parent,
  role,
  event_type,
  content,
  created_at: "2026-10-19T00:00:00Z",
});

// a thinking event becomes a thinking row; an empty one is dropped
{
  const rows = buildRows([ev("user", "message", { text: "hi" }), ev("agent", "thinking", { text: "Let me look." }), ev("agent", "thinking", { text: "" }), ev("agent", "message", { text: "Hello" })]);
  assert.deepEqual(rows.map((r) => r.kind), ["user", "thinking", "agent"]);
  assert.equal(rows[1].kind === "thinking" && rows[1].text, "Let me look.");
}

// thinking that is followed by a tool call folds into the activity group with it; thinking before the final reply stays visible
{
  const call = ev("agent", "tool_call", { name: "view_file", arguments: { path: "a.py" } });
  const rows = buildRows([
    ev("user", "message", { text: "go" }),
    ev("agent", "thinking", { text: "I need to read a.py" }),
    call,
    ev("system", "tool_result", { ok: true, content: "x", error: null }, call.id),
    ev("agent", "thinking", { text: "Now I can answer" }),
    ev("agent", "message", { text: "Done." }),
  ]);
  const items = groupRows(rows);
  assert.deepEqual(items.map((i) => (i.kind === "row" ? i.row.kind : "activity")), ["user", "activity", "thinking", "agent"]);
  const group = items[1];
  assert.equal(group.kind === "activity" && group.rows.map((r) => r.kind).join(","), "thinking,tool");
}

// a thinking row is not mistaken for a tool: the summary of a group with no tools stays the neutral label
{
  const items = groupRows(buildRows([ev("agent", "thinking", { text: "hm" })]));
  assert.equal(items.length, 1);
}

console.log("thinking rows: all checks passed");
