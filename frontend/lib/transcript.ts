import type { SessionEvent } from "./types";

/**
 * Pure helpers over a session's event log (Phase 3, §16). Kept free of React so the rules —
 * which events render, how a tool call pairs with its result, which approval is still open — can
 * be exercised on their own.
 *
 * The event vocabulary (from backend/app/services/agent_loop.py):
 *   message, user_interrupt            — what the person and the agent said
 *   tool_call                          — agent; content { name, arguments, read_only, call_id, step }
 *   tool_result                        — system; parent_event_id → the tool_call; { ok, content, error }
 *   approval_request                   — system; parent → the tool_call; { approval_request_id, action_type, payload }
 *   approval_response                  — user;   parent → the approval_request; { approved }
 *   error, stuck_notice                — system notices
 *   project_knowledge_injected, condensation_summary — bookkeeping; never shown
 */
export type Row =
  | { kind: "user"; id: number; text: string; interrupt: boolean; attachments: RowAttachment[] }
  | { kind: "agent"; id: number; text: string }
  | { kind: "tool"; id: number; name: string; arguments: Record<string, unknown>; result: { ok: boolean; content: string; error: string | null } | null }
  | { kind: "approval"; id: number; approvalId: string; actionType: string; payload: Record<string, unknown>; answered: boolean | null }
  | { kind: "error"; id: number; text: string }
  | { kind: "notice"; id: number; text: string; severity: "soft" | "hard" };

/** Metadata of a picture sent with a user message (Phase 6.1) — never the pixels; see attachmentObjectUrl. */
export interface RowAttachment {
  id: string;
  filename: string;
  width: number;
  height: number;
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** The attachments the server wrote on a user message/interrupt event's content ([] if none). */
export function rowAttachments(content: Record<string, unknown> | null | undefined): RowAttachment[] {
  const items = content?.attachments;
  if (!Array.isArray(items)) return [];
  const out: RowAttachment[] = [];
  for (const a of items) {
    if (a && typeof a === "object" && typeof (a as Record<string, unknown>).id === "string") {
      const r = a as Record<string, unknown>;
      out.push({ id: r.id as string, filename: str(r.filename) || "image", width: Number(r.width) || 0, height: Number(r.height) || 0 });
    }
  }
  return out;
}

export function buildRows(events: SessionEvent[]): Row[] {
  const results = new Map<number, SessionEvent>();
  const responses = new Map<number, SessionEvent>();
  for (const e of events) {
    if (e.event_type === "tool_result" && e.parent_event_id != null) results.set(e.parent_event_id, e);
    if (e.event_type === "approval_response" && e.parent_event_id != null) responses.set(e.parent_event_id, e);
  }

  const rows: Row[] = [];
  for (const e of events) {
    const c = e.content ?? {};
    switch (e.event_type) {
      case "message":
        rows.push(e.role === "user" ? { kind: "user", id: e.id, text: str(c.text), interrupt: false, attachments: rowAttachments(c) } : { kind: "agent", id: e.id, text: str(c.text) });
        break;
      case "user_interrupt":
        rows.push({ kind: "user", id: e.id, text: str(c.text), interrupt: true, attachments: rowAttachments(c) });
        break;
      case "tool_call": {
        const r = results.get(e.id);
        rows.push({
          kind: "tool",
          id: e.id,
          name: str(c.name),
          arguments: (c.arguments as Record<string, unknown>) ?? {},
          result: r ? { ok: Boolean(r.content.ok), content: str(r.content.content), error: typeof r.content.error === "string" ? r.content.error : null } : null,
        });
        break;
      }
      case "approval_request": {
        const response = responses.get(e.id);
        rows.push({
          kind: "approval",
          id: e.id,
          approvalId: str(c.approval_request_id),
          actionType: str(c.action_type),
          payload: (c.payload as Record<string, unknown>) ?? {},
          answered: response ? Boolean(response.content.approved) : null,
        });
        break;
      }
      case "error":
        rows.push({ kind: "error", id: e.id, text: str(c.text) });
        break;
      case "stuck_notice":
        rows.push({ kind: "notice", id: e.id, text: str(c.text), severity: c.severity === "hard" ? "hard" : "soft" });
        break;
      default:
        // tool_result (shown inside its tool row), approval_response (folded into its approval row),
        // project_knowledge_injected, condensation_summary: nothing of their own to render.
        break;
    }
  }
  return rows;
}

/** The approval the person still has to answer, if any: the latest approval row nobody has answered. */
export function pendingApproval(rows: Row[]): Extract<Row, { kind: "approval" }> | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (r.kind === "approval" && r.answered === null) return r;
  }
  return null;
}

/** Has the agent said or done anything yet? (The setup card goes away once it has.) */
export function agentHasStarted(events: SessionEvent[]): boolean {
  return events.some((e) => e.role !== "user");
}

/** The last thing the person typed, for "Retry" after an error row. */
export function lastUserText(events: SessionEvent[]): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.role === "user" && (e.event_type === "message" || e.event_type === "user_interrupt")) {
      const t = e.content?.text;
      if (typeof t === "string" && t) return t;
    }
  }
  return null;
}

/** One line for a tool call's collapsed row: "view_file · src/app.py". */
export function toolSummary(name: string, args: Record<string, unknown>): string {
  const hint = ["path", "file_path", "command", "query", "pattern", "url"].map((k) => args[k]).find((v) => typeof v === "string") as string | undefined;
  if (!hint) return name;
  const oneLine = hint.replace(/\s+/g, " ");
  return `${name} · ${oneLine.length > 60 ? `${oneLine.slice(0, 59)}…` : oneLine}`;
}

/** Human description of what an approval asks for. */
export function describeApproval(actionType: string, payload: Record<string, unknown>): { title: string; detail: string } {
  if (actionType === "execute_bash_escalation") {
    const reason = str(payload.guard_reason);
    return { title: "Run a command that needs your OK", detail: [str(payload.command), reason && `Why: ${reason}`].filter(Boolean).join("\n") };
  }
  if (actionType.startsWith("mcp_tool:")) {
    const [, server = "", tool = ""] = actionType.split(":");
    return { title: `Use ${tool || "a tool"} on ${server || "a connector"}`, detail: JSON.stringify(payload.arguments ?? {}, null, 2) };
  }
  if (actionType.startsWith("scheduled_tool:")) {
    return { title: `Scheduled run wants to use ${actionType.slice("scheduled_tool:".length)}`, detail: JSON.stringify(payload, null, 2) };
  }
  return { title: "The agent is asking for approval", detail: JSON.stringify(payload, null, 2) };
}
