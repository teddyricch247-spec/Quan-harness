"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Checkpoint, Project } from "@/lib/types";
import EmptyState from "./EmptyState";
import ErrorBanner from "./ErrorBanner";
import Sheet from "./Sheet";

/** ⋯ → Checkpoints. Converted from WorkspaceSyncPanel (Phase Convert, C7); restore logic unchanged. */
export default function CheckpointsSheet({
  open,
  onClose,
  project,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  onDone: () => void;
}) {
  const [checkpoints, setCheckpoints] = useState<Checkpoint[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<Checkpoint[]>(`/projects/${project.id}/checkpoints`)
      .then(setCheckpoints)
      .catch((e: ApiError) => setError(e.message));
  }, [project.id]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function restore(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await apiFetch(`/checkpoints/${id}/restore`, { method: "POST" });
      load();
      onDone();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Checkpoints">
      <div className="px-4 pt-3">
        <ErrorBanner message={error} />
      </div>
      {checkpoints === null && !error && <p className="px-4 py-3 text-sm text-muted">Loading…</p>}
      {checkpoints?.length === 0 && (
        <EmptyState title="No checkpoints yet">
          They appear automatically as the agent edits files or runs commands in a session.
        </EmptyState>
      )}
      <ul>
        {checkpoints?.map((cp) => (
          <li key={cp.id} className="row">
            <span className="flex-1 mono text-xs text-muted">
              {cp.git_commit_sha.slice(0, 7)} — {new Date(cp.created_at).toLocaleString()}
            </span>
            <button
              className="btn-default text-xs disabled:opacity-40"
              disabled={!cp.restorable || busyId !== null}
              title={!cp.restorable ? "Only the session that most recently edited this workspace can restore" : undefined}
              onClick={() => restore(cp.id)}
            >
              {busyId === cp.id ? "Restoring…" : "Restore"}
            </button>
          </li>
        ))}
      </ul>
    </Sheet>
  );
}
