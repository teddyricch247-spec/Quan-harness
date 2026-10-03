"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { DeployNeedsConfirmationResult, DeployRun, DeployTarget, DeployTriggerResult, Project } from "@/lib/types";

// Phase 5.1/5.2/5.5 (§23.5/§23.6/§23.9). Polling rather than the backend's
// own /deploy/stream SSE endpoint — routers/deploy.py's stream endpoint
// requires the same Bearer-header auth every other endpoint does, which
// native EventSource can't send, and this codebase hasn't solved that for
// its one other SSE endpoint (routers/agent.py's stream_session) either —
// no frontend page consumes that one yet. Polling every POLL_MS while a
// deploy is running is a real, working v1; a fetch()-based streaming reader
// (which, unlike EventSource, can carry an Authorization header) is the
// natural upgrade path once the chat transcript UI takes on the same
// problem for the agent stream — see /docs/PHASE5_1_5_2_5_5_NOTES.md.
const POLL_MS = 2000;
const DIAGNOSIS_WAIT_MS = 90_000;

const PHASE_LABEL: Record<DeployRun["phase"], string> = {
  detect: "Detecting stack…",
  build: "Building…",
  start: "Starting…",
  healthy: "Running",
};

export default function DeployPanel({ project, onProjectChanged }: { project: Project; onProjectChanged: () => void }) {
  const [runs, setRuns] = useState<DeployRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<DeployTarget[] | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function refreshRuns() {
    apiFetch<DeployRun[]>(`/projects/${project.id}/deploy/runs`)
      .then(setRuns)
      .catch(() => {});
  }

  useEffect(() => {
    refreshRuns();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [project.id]);

  const latest = runs[0] ?? null;

  useEffect(() => {
    // The raw log lands the moment a run fails; the diagnosis is written a few
    // seconds later (§23.9 point 2). Keep polling briefly after a failure so it
    // shows up on its own — but stop after DIAGNOSIS_WAIT_MS, since a diagnosis
    // can legitimately never arrive (no LLM credential, provider down).
    const diagnosisPending =
      !!latest &&
      latest.status === "failed" &&
      !latest.diagnosis_text &&
      !!latest.completed_at &&
      Date.now() - new Date(latest.completed_at).getTime() < DIAGNOSIS_WAIT_MS;
    const anyRunning = runs.some((r) => r.status === "running") || diagnosisPending;
    if (anyRunning && !pollRef.current) {
      pollRef.current = setInterval(refreshRuns, POLL_MS);
    } else if (!anyRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  async function handleDeploy(forceRedetect = false) {
    setBusy(true);
    setError(null);
    setProposal(null);
    try {
      const result = await apiFetch<DeployTriggerResult | DeployNeedsConfirmationResult>(
        `/projects/${project.id}/deploy`,
        { method: "POST", body: JSON.stringify({ force_redetect: forceRedetect }) }
      );
      if ("needs_confirmation" in result) {
        setProposal(result.proposed_targets);
      } else {
        refreshRuns();
        if (!pollRef.current) pollRef.current = setInterval(refreshRuns, POLL_MS);
      }
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(targets: DeployTarget[]) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${project.id}/deploy/targets/confirm`, {
        method: "POST",
        body: JSON.stringify({ targets: targets.map((t) => ({ name: t.name, root: t.root })) }),
      });
      setProposal(null);
      onProjectChanged();
      handleDeploy();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <p className="text-sm font-medium mb-2">Deploy</p>

      {error && <p className="text-sm text-red-700 mb-3">{error}</p>}

      {proposal ? (
        <TargetConfirmation
          proposal={proposal}
          busy={busy}
          onConfirm={handleConfirm}
          onCancel={() => setProposal(null)}
        />
      ) : (
        <>
          <div className="flex gap-2 mb-3">
            <button className="btn-primary disabled:opacity-40" disabled={busy || latest?.status === "running"} onClick={() => handleDeploy(false)}>
              {latest?.status === "running" ? "Deploying…" : "Deploy"}
            </button>
            {project.deploy_targets_confirmed && (
              <button
                className="btn-default text-xs disabled:opacity-40"
                disabled={busy || latest?.status === "running"}
                title="Re-detect the build plan instead of reusing what was last confirmed"
                onClick={() => handleDeploy(true)}
              >
                Re-detect
              </button>
            )}
          </div>

          {project.deploy_targets.length > 0 && (
            <p className="text-sm text-muted mb-3">
              {project.deploy_targets.map((t) => (
                <span key={t.name} className="mono mr-2">
                  {t.name}: {t.stack ?? "not yet detected"}
                  {t.port ? ` :${t.port}` : ""}
                </span>
              ))}
            </p>
          )}

          {latest && <RunStatus run={latest} />}
        </>
      )}
    </div>
  );
}

function TargetConfirmation({
  proposal,
  busy,
  onConfirm,
  onCancel,
}: {
  proposal: DeployTarget[];
  busy: boolean;
  onConfirm: (targets: DeployTarget[]) => void;
  onCancel: () => void;
}) {
  const [targets, setTargets] = useState(proposal);

  function updateField(index: number, field: "name" | "root", value: string) {
    setTargets((prev) => prev.map((t, i) => (i === index ? { ...t, [field]: value } : t)));
  }

  return (
    <div className="border border-amber-400 bg-amber-50 rounded p-3 mb-3 text-sm">
      <p className="mb-2">
        This looks like it might have more than one deployable part. Confirm the roots below (only needs doing
        once — §23.6) before the first deploy.
      </p>
      <div className="space-y-2 mb-3">
        {targets.map((t, i) => (
          <div key={i} className="flex gap-2 items-center">
            <input
              className="border rounded px-2 py-1 text-sm w-32"
              value={t.name}
              onChange={(e) => updateField(i, "name", e.target.value)}
              placeholder="name"
            />
            <input
              className="border rounded px-2 py-1 text-sm flex-1 mono"
              value={t.root}
              onChange={(e) => updateField(i, "root", e.target.value)}
              placeholder="path relative to repo root"
            />
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button className="btn-primary disabled:opacity-40" disabled={busy} onClick={() => onConfirm(targets)}>
          Confirm and deploy
        </button>
        <button className="btn-default" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function RunStatus({ run }: { run: DeployRun }) {
  const [copied, setCopied] = useState(false);
  const log = [run.stdout, run.stderr].filter(Boolean).join("\n\n");

  return (
    <div className="text-sm">
      <p className="mb-1">
        <span className={`inline-block h-2 w-2 rounded-full mr-2 ${DOT[run.status]}`} />
        {run.target_name && <span className="mono mr-1">{run.target_name}:</span>}
        {run.status === "running" ? PHASE_LABEL[run.phase] : run.status === "success" ? "Deployed" : "Failed"}
      </p>

      {run.status === "failed" && run.diagnosis_text && (
        <div className="border rounded p-3 mb-2 bg-neutral-50">
          {run.failure_class === "environment" && (
            <p className="text-xs font-medium text-amber-800 mb-1">
              Environment issue — not a code bug, so there is nothing for the agent to fix here.
              {run.environment_kind && " See Preview notices below for what you can do about it."}
            </p>
          )}
          <p className="mb-2">{run.diagnosis_text}</p>
          {run.suggested_fix_prompt && (
            <div className="flex items-start gap-2">
              <code className="mono text-xs flex-1 bg-white border rounded px-2 py-1">{run.suggested_fix_prompt}</code>
              <button
                className="btn-default text-xs"
                onClick={() => {
                  navigator.clipboard.writeText(run.suggested_fix_prompt || "");
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          )}
        </div>
      )}

      {log && (
        <pre className="mono text-xs bg-neutral-900 text-neutral-100 rounded p-3 overflow-x-auto max-h-48 overflow-y-auto">
          {log}
        </pre>
      )}
    </div>
  );
}

const DOT: Record<DeployRun["status"], string> = {
  running: "bg-amber-500",
  success: "bg-green-600",
  failed: "bg-red-600",
};
