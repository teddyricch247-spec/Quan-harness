"use client";

import { useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { DeployNeedsConfirmationResult, DeployRun, DeployTarget, DeployTriggerResult, Project } from "@/lib/types";
import Sheet from "./Sheet";

// Phase 5.1/5.2/5.5 (§23.5/§23.6/§23.9), converted from DeployPanel by Phase Convert (C7): same
// calls, same monorepo target confirmation, same failure diagnosis. The runs themselves now come
// from useDeployRuns (lifted so the Preview tab's status line reads the same list).

export const PHASE_LABEL: Record<DeployRun["phase"], string> = {
  detect: "Detecting stack…",
  build: "Building…",
  start: "Starting…",
  healthy: "Running",
};

const DOT: Record<DeployRun["status"], string> = {
  running: "bg-warn",
  success: "bg-ok",
  failed: "bg-brand",
};

export default function DeploySheet({
  open,
  onClose,
  project,
  runs,
  onRunsChanged,
  onProjectChanged,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  runs: DeployRun[];
  onRunsChanged: () => void; // a deploy was triggered: start polling
  onProjectChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proposal, setProposal] = useState<DeployTarget[] | null>(null);
  const latest = runs[0] ?? null;
  const running = latest?.status === "running";

  async function deploy(forceRedetect = false) {
    setBusy(true);
    setError(null);
    setProposal(null);
    try {
      const result = await apiFetch<DeployTriggerResult | DeployNeedsConfirmationResult>(`/projects/${project.id}/deploy`, {
        method: "POST",
        body: JSON.stringify({ force_redetect: forceRedetect }),
      });
      if ("needs_confirmation" in result) setProposal(result.proposed_targets);
      else onRunsChanged();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(targets: DeployTarget[]) {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${project.id}/deploy/targets/confirm`, {
        method: "POST",
        body: JSON.stringify({ targets: targets.map((t) => ({ name: t.name, root: t.root })) }),
      });
      setProposal(null);
      onProjectChanged();
      deploy();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Deploy" wide>
      <div className="p-4">
        {error && <p className="text-sm text-accent mb-3">{error}</p>}

        {proposal ? (
          <TargetConfirmation proposal={proposal} busy={busy} onConfirm={confirm} onCancel={() => setProposal(null)} />
        ) : (
          <>
            <div className="flex gap-2 mb-3">
              <button className="btn-primary disabled:opacity-40" disabled={busy || running} onClick={() => deploy(false)}>
                {running ? "Deploying…" : latest ? "Deploy again" : "Deploy"}
              </button>
              {project.deploy_targets_confirmed && (
                <button
                  className="btn-default text-xs disabled:opacity-40"
                  disabled={busy || running}
                  title="Re-detect the build plan instead of reusing what was last confirmed"
                  onClick={() => deploy(true)}
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

            {latest ? <RunStatus run={latest} /> : <p className="text-sm text-muted">Not deployed yet.</p>}
          </>
        )}
      </div>
    </Sheet>
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
    <div className="border border-warn bg-warn-soft rounded-xl p-3 text-sm">
      <p className="mb-2">
        This looks like it might have more than one deployable part. Confirm the roots below (only needs doing once — §23.6) before the
        first deploy.
      </p>
      <div className="space-y-2 mb-3">
        {targets.map((t, i) => (
          <div key={i} className="flex gap-2 items-center">
            <input className="input w-32" value={t.name} onChange={(e) => updateField(i, "name", e.target.value)} placeholder="name" aria-label="Target name" />
            <input className="input flex-1 mono" value={t.root} onChange={(e) => updateField(i, "root", e.target.value)} placeholder="path relative to repo root" aria-label="Target root" />
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
        <div className="border rounded-xl p-3 mb-2 bg-paper">
          {run.failure_class === "environment" && (
            <p className="text-xs font-medium text-warn mb-1">
              Environment issue — not a code bug, so there is nothing for the agent to fix here.
              {run.environment_kind && " See the notices on the Preview tab for what you can do about it."}
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
        <pre className="mono text-xs bg-neutral-900 text-neutral-100 rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto">{log}</pre>
      )}
    </div>
  );
}
