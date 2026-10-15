"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Session } from "@/lib/types";
import { CheckIcon } from "./icons";
import EmptyState from "./EmptyState";
import ErrorBanner from "./ErrorBanner";
import Sheet from "./Sheet";

function statusColor(s: Session["status"]) {
  if (s === "completed") return "text-ok";
  if (s === "failed" || s === "stuck") return "text-accent";
  if (s === "waiting_approval") return "text-warn";
  return "text-muted";
}

/**
 * Phase Convert (C4, "What happens to Sessions?"): the project title opens this sheet. It replaces
 * the Sessions page — list, **New session** with an optional title, scheduled sessions labeled.
 * Tapping a session switches the workspace's chat pane to it.
 */
export default function SessionsSheet({
  open,
  onClose,
  projectId,
  activeSessionId,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  activeSessionId: string | null;
  onSelect: (session: Session) => void;
}) {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    apiFetch<Session[]>(`/projects/${projectId}/sessions`)
      .then(setSessions)
      .catch((e: ApiError) => setError(e.message));
  }, [projectId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function createSession() {
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<Session>(`/projects/${projectId}/sessions`, {
        method: "POST",
        body: JSON.stringify({ title: title.trim() || undefined }),
      });
      setTitle("");
      onSelect(created);
      onClose();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Sessions">
      <div className="p-4 border-b border-line">
        <ErrorBanner message={error} />
        <div className="flex gap-2">
          <input
            className="input"
            placeholder="Optional title"
            value={title}
            aria-label="Session title"
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && createSession()}
          />
          <button className="btn-primary whitespace-nowrap" disabled={busy} onClick={createSession}>
            New session
          </button>
        </div>
      </div>

      {sessions === null && !error && <p className="px-4 py-3 text-sm text-muted">Loading…</p>}
      {sessions?.length === 0 && <EmptyState title="No sessions yet">Send a message to start one, or create one above.</EmptyState>}
      <ul>
        {sessions
          ?.filter((s) => s.status !== "archived")
          .map((s) => (
            <li key={s.id}>
              <button
                className="row"
                aria-current={s.id === activeSessionId ? "true" : undefined}
                onClick={() => {
                  onSelect(s);
                  onClose();
                }}
              >
                <span className="flex-1 min-w-0">
                  <span className="block truncate text-sm font-medium">{s.title ?? "Untitled session"}</span>
                  <span className="block text-xs text-muted">{timeAgo(s.updated_at || s.created_at)}</span>
                </span>
                {/* Phase 4.5 (§26) — started by a project_schedules row rather than a person's own
                    message; everything else about it (status, turn loop, approvals) is identical. */}
                {s.trigger === "scheduled" && <span className="text-xs text-muted border border-line rounded px-1.5 py-0.5">Scheduled</span>}
                {s.read_only && <span className="text-xs text-muted border border-line rounded px-1.5 py-0.5">Read-only</span>}
                <span className={`text-xs font-medium ${statusColor(s.status)}`}>{s.status.replace("_", " ")}</span>
                {s.id === activeSessionId && <CheckIcon />}
              </button>
            </li>
          ))}
      </ul>
    </Sheet>
  );
}
