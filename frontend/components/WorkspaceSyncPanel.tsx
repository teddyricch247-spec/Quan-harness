"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { Checkpoint, Project, PullResult, PushResult, Workspace } from "@/lib/types";

const BILLING_LABEL: Record<Workspace["billing_state"], string> = {
  running: "Running",
  warm: "Starting…",
  cold: "Sleeping (no compute billed)",
};

const BILLING_DOT: Record<Workspace["billing_state"], string> = {
  running: "bg-green-600",
  warm: "bg-amber-500",
  cold: "bg-neutral-400",
};

export default function WorkspaceSyncPanel({ project }: { project: Project }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"push" | "pull" | "restore" | null>(null);
  const [pushResult, setPushResult] = useState<PushResult | null>(null);
  const [pullWarning, setPullWarning] = useState<PullResult | null>(null);

  function refresh() {
    apiFetch<Workspace>(`/projects/${project.id}/workspace`).then(setWorkspace).catch(() => {});
    apiFetch<Checkpoint[]>(`/projects/${project.id}/checkpoints`).then(setCheckpoints).catch(() => {});
  }

  useEffect(refresh, [project.id]);

  async function handlePush() {
    setBusy("push");
    setError(null);
    setPushResult(null);
    try {
      const result = await apiFetch<PushResult>(`/projects/${project.id}/push`, { method: "POST", body: "{}" });
      setPushResult(result);
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function handlePull(confirmDiscard: boolean) {
    setBusy("pull");
    setError(null);
    try {
      const result = await apiFetch<PullResult>(`/projects/${project.id}/pull`, {
        method: "POST",
        body: JSON.stringify({ confirm_discard: confirmDiscard }),
      });
      if (result.needs_confirmation) {
        setPullWarning(result);
      } else {
        setPullWarning(null);
        refresh();
      }
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleRestore(checkpointId: string) {
    setBusy("restore");
    setError(null);
    try {
      await apiFetch(`/checkpoints/${checkpointId}/restore`, { method: "POST" });
      refresh();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="card">
      <p className="text-sm font-medium mb-2">Workspace &amp; sync</p>

      <div className="flex items-center gap-2 mb-3 text-sm text-muted">
        <span className={`inline-block h-2 w-2 rounded-full ${workspace ? BILLING_DOT[workspace.billing_state] : "bg-neutral-300"}`} />
        {workspace ? BILLING_LABEL[workspace.billing_state] : "Loading…"}
        {workspace && !workspace.provisioned && " — not yet provisioned (happens on first use)"}
      </div>

      {error && <ErrorLine message={error} />}

      <div className="flex gap-2 mb-3">
        <button className="btn-primary disabled:opacity-40" disabled={busy !== null} onClick={handlePush}>
          {busy === "push" ? "Pushing…" : "Push"}
        </button>
        <button
          className="btn-default disabled:opacity-40"
          disabled={busy !== null || !project.github_repo}
          onClick={() => handlePull(false)}
          title={!project.github_repo ? "No linked repository yet — push first" : undefined}
        >
          {busy === "pull" ? "Pulling…" : "Pull"}
        </button>
      </div>

      {pushResult && (
        <div className="text-sm text-muted mb-3">
          Pushed to <span className="mono">{pushResult.full_name}</span>@
          <span className="mono">{pushResult.branch}</span> ({pushResult.commit_sha.slice(0, 7)}).
          {pushResult.pull_request_url && (
            <>
              {" "}
              <a className="underline" href={pushResult.pull_request_url} target="_blank" rel="noreferrer">
                View pull request
              </a>
            </>
          )}
        </div>
      )}

      {pullWarning && (
        <div className="border border-amber-400 bg-amber-50 rounded p-3 mb-3 text-sm">
          <p className="mb-2">
            Pulling will overwrite the workspace with what's on{" "}
            <span className="mono">{pullWarning.branch}</span>, discarding any local changes that
            haven't been pushed. This can't be undone.
          </p>
          <div className="flex gap-2">
            <button className="btn-danger" disabled={busy !== null} onClick={() => handlePull(true)}>
              Discard local changes and pull
            </button>
            <button className="btn-default" onClick={() => setPullWarning(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      <p className="text-sm font-medium mb-1">Checkpoints</p>
      {checkpoints.length === 0 ? (
        <p className="text-sm text-muted">
          None yet — checkpoints appear automatically as file edits or shell commands run in a
          session (§23.4). No agent exists yet in this phase, so this list stays empty until one does.
        </p>
      ) : (
        <ul className="space-y-1">
          {checkpoints.map((cp) => (
            <li key={cp.id} className="flex items-center justify-between text-sm">
              <span className="mono text-muted">
                {cp.git_commit_sha.slice(0, 7)} — {new Date(cp.created_at).toLocaleString()}
              </span>
              <button
                className="btn-default text-xs disabled:opacity-40"
                disabled={!cp.restorable || busy !== null}
                title={!cp.restorable ? "Only the session that most recently edited this workspace can restore" : undefined}
                onClick={() => handleRestore(cp.id)}
              >
                {busy === "restore" ? "Restoring…" : "Restore"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return <p className="text-sm text-red-700 mb-3">{message}</p>;
}
