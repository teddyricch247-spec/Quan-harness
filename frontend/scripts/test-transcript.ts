// Run: npx tsx scripts/test-transcript.ts
// Checks the rules that decide what the chat folds into "Read a file, ran 10 commands" and what stays visible.
import assert from "node:assert/strict";
import { activitySummary, buildRows, failedToolCount, groupRows, latestToolLine, Row } from "../lib/transcript";
import type { SessionEvent } from "../lib/types";

let n = 0;
const ok = (name: string, fn: () => void) => {
  fn();
  n++;
  console.log("ok", name);
};

let id = 0;
const user = (text = "go"): Row => ({ kind: "user", id: ++id, text, interrupt: false, attachments: [] });
const agent = (text: string): Row => ({ kind: "agent", id: ++id, text });
const tool = (name: string, args: Record<string, unknown> = {}, result: { ok: boolean } | null = { ok: true }): Row => ({
  kind: "tool", id: ++id, name, arguments: args, result: result ? { ok: result.ok, content: "", error: null } : null,
});
const approval = (answered: boolean | null): Row => ({ kind: "approval", id: ++id, approvalId: `a${id}`, actionType: "execute_bash_escalation", payload: {}, answered });
const error = (): Row => ({ kind: "error", id: ++id, text: "boom" });
const shape = (rows: Row[]) => groupRows(rows).map((i) => (i.kind === "row" ? i.row.kind : `[${i.rows.map((r) => r.kind).join(",")}]`)).join(" ");

ok("a plain reply is not folded", () => {
  assert.equal(shape([user(), agent("Hi!")]), "user agent");
});

ok("tool calls fold; the final reply stays visible", () => {
  assert.equal(shape([user(), tool("view_file"), tool("create_file"), agent("Done.")]), "user [tool,tool] agent");
});

ok("narration between tool calls folds into the group", () => {
  assert.equal(shape([user(), agent("I'll start."), tool("create_file"), agent("Now checking."), tool("execute_bash"), agent("All set.")]), "user [agent,tool,agent,tool] agent");
});

ok("the screenshot turn: work, an approval, more work, then the reply", () => {
  const rows = [user("create a hello world html"), agent("Plan."), tool("create_file"), agent("Sanity-check."), tool("execute_bash"), approval(true), tool("execute_bash"), agent("CDN ok."), tool("str_replace"), agent("Done — open the Preview tab.")];
  assert.equal(shape(rows), "user [agent,tool,agent,tool] approval [tool,agent,tool] agent");
});

ok("a pending approval stays visible, and narration before it folds", () => {
  const rows = [user(), agent("I need to run this."), tool("execute_bash", {}, null), approval(null)];
  assert.equal(shape(rows), "user [agent,tool] approval");
  const items = groupRows(rows);
  assert.equal(items[items.length - 1].kind, "row");
});

ok("errors and notices are never folded, and end the group", () => {
  const notice: Row = { kind: "notice", id: ++id, text: "stuck", severity: "soft" };
  assert.equal(shape([user(), tool("view_file"), error(), tool("view_file"), notice]), "user [tool] error [tool] notice");
});

ok("a new user message starts a new turn: earlier text is not folded by later tools", () => {
  assert.equal(shape([user(), agent("Looking."), user("wait"), tool("view_file"), agent("Found it.")]), "user agent user [tool] agent");
});

ok("a group keeps its id as it grows (so an opened group stays open)", () => {
  const rows = [user(), tool("view_file"), tool("create_file"), tool("execute_bash")];
  const ids = [2, 3, 4].map((k) => {
    const it = groupRows(rows.slice(0, k))[1];
    return it.kind === "activity" ? it.id : -1;
  });
  assert.deepEqual(new Set(ids).size, 1);
});

ok("reply text that later gets a tool after it becomes part of the group", () => {
  const before = groupRows([user(), tool("view_file"), agent("Let me also check…")]);
  assert.equal(before[before.length - 1].kind, "row");
  const after = groupRows([user(), tool("view_file"), agent("Let me also check…"), tool("view_file")]);
  assert.equal(after.length, 2);
  assert.equal(after[1].kind, "activity");
});

ok("summary wording", () => {
  assert.equal(activitySummary([tool("view_file", { path: "a.py" })]), "Read a file");
  const mixed = [tool("view_file", { path: "a" }), ...Array.from({ length: 10 }, () => tool("execute_bash"))];
  assert.equal(activitySummary(mixed), "Read a file, ran 10 commands");
  assert.equal(activitySummary([tool("str_replace", { path: "i.html" }), tool("str_replace", { path: "i.html" }), tool("str_replace", { path: "i.html" })]), "Edited a file");
  assert.equal(activitySummary([tool("str_replace", { path: "a" }), tool("str_replace", { path: "b" })]), "Edited 2 files");
  assert.equal(activitySummary([tool("create_file", { path: "i.html" }), tool("execute_bash")]), "Created a file, ran a command");
  assert.equal(activitySummary([tool("browser_click"), tool("browser_type"), tool("browser_navigate")]), "Used the browser 3 times");
  assert.equal(activitySummary([tool("preview_rebuild"), tool("run_tests")]), "Rebuilt the preview, ran a check");
  assert.equal(activitySummary([tool("mystery")]), "Used a tool");
  assert.equal(activitySummary([agent("just notes")]), "Agent notes");
});

ok("summary order follows what happened first", () => {
  assert.equal(activitySummary([tool("execute_bash"), tool("view_file", { path: "x" })]), "Ran a command, read a file");
});

ok("failed count and latest line", () => {
  const rows = [tool("view_file", { path: "a" }), tool("execute_bash", { command: "ls -la" }, { ok: false }), tool("str_replace", { path: "b.html" }, null)];
  assert.equal(failedToolCount(rows), 1);
  assert.equal(latestToolLine(rows), "str_replace · b.html");
  assert.equal(latestToolLine([agent("x")]), null);
});

ok("works on rows built from real events (call + result pairing)", () => {
  const ev = (i: number, role: SessionEvent["role"], event_type: string, content: Record<string, unknown>, parent: number | null = null): SessionEvent =>
    ({ id: i, session_id: "s", parent_event_id: parent, role, event_type, content, created_at: "" });
  const events = [
    ev(1, "user", "message", { text: "hello world page" }),
    ev(2, "agent", "tool_call", { name: "create_file", arguments: { path: "index.html" } }),
    ev(3, "system", "tool_result", { ok: true, content: "created" }, 2),
    ev(4, "agent", "tool_call", { name: "execute_bash", arguments: { command: "node --check x" } }),
    ev(5, "system", "tool_result", { ok: false, content: "", error: "nope" }, 4),
    ev(6, "agent", "message", { text: "Made index.html." }),
  ];
  const items = groupRows(buildRows(events));
  assert.equal(items.length, 3);
  const g = items[1];
  assert.equal(g.kind, "activity");
  if (g.kind === "activity") {
    assert.equal(activitySummary(g.rows), "Created a file, ran a command");
    assert.equal(failedToolCount(g.rows), 1);
  }
});

console.log(`\n${n} transcript checks passed`);
