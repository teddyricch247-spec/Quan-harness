"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Project, PullResult } from "@/lib/types";
import ErrorBanner from "./ErrorBanner";
import Sheet from "./Sheet";

/**
 * ⋯ → Pull. Converted from WorkspaceSyncPanel (Phase Convert, C7) with the logic unchanged,
 * including the "Discard local changes and pull" confirmation. `autoRun` starts a pull the moment
 * the sheet opens — that is what the workspace's "Retry pull" banner (a failed first import pull,
 * C4) does, so the person doesn't have to find the button again.
 */
export default function PullSheet({
  open,
  onClose,
  project,
  onDone,
  autoRun = false,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  onDone: () => void;
  autoRun?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<PullResult | null>(null);
  const [done, setDone] = useState(false);
  const ranFor = useRef<boolean>(false);

  async function pull(confirmDiscard: boolean) {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const result = await apiFetch<PullResult>(`/projects/${project.id}/pull`, {
        method: "POST",
        body: JSON.stringify({ confirm_discard: confirmDiscard }),
      });
      if (result.needs_confirmation) {
        setWarning(result);
      } else {
        setWarning(null);
        setDone(true);
        onDone();
      }
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!open) {
      ranFor.current = false;
      return;
    }
    if (autoRun && !ranFor.current) {
      ranFor.current = true;
      pull(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, autoRun]);

  return (
    <Sheet open={open} onClose={onClose} title="Pull">
      <div className="p-4 space-y-3">
        <p className="text-sm text-muted">
          Makes the workspace match <span className="mono">{project.github_default_branch ?? "the default branch"}</span> on GitHub.
        </p>
        {!project.github_repo && <p className="text-sm">No linked repository yet — push first.</p>}
        <ErrorBanner message={error} />
        {done && <p className="text-sm text-ok">Pulled.</p>}
        {warning && (
          <div className="border border-warn bg-warn-soft rounded-xl p-3 text-sm">
            <p className="mb-2">
              Pulling will overwrite the workspace with what’s on <span className="mono">{warning.branch}</span>, discarding any local changes that
              haven’t been pushed. This can’t be undone.
            </p>
            <div className="flex gap-2">
              <button className="btn-danger" disabled={busy} onClick={() => pull(true)}>
                Discard local changes and pull
              </button>
              <button className="btn-default" onClick={() => setWarning(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {!warning && (
          <button className="btn-primary w-full disabled:opacity-40" disabled={busy || !project.github_repo} onClick={() => pull(false)}>
            {busy ? "Pulling…" : "Pull"}
          </button>
        )}
      </div>
    </Sheet>
  );
}
