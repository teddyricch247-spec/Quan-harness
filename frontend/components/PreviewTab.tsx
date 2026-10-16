"use client";

import type { DeployRun, Project } from "@/lib/types";
import EmptyState from "./EmptyState";
import { PHASE_LABEL } from "./DeploySheet";
import PreviewNotices from "./PreviewNotices";
import PreviewPanel from "./PreviewPanel";

/**
 * The workspace's Preview tab (Phase Convert, C4/C7): the deploy state on one line with a Deploy
 * button, then the live preview and its notices. Before the first deploy it says so instead of
 * showing an empty frame ("Not deployed yet", with Deploy right there — C3 #6).
 */
export default function PreviewTab({
  project,
  runs,
  runsLoaded,
  onDeploy,
  onOpenSecrets,
  refreshSignal,
}: {
  project: Project;
  runs: DeployRun[];
  runsLoaded: boolean;
  onDeploy: () => void;
  onOpenSecrets: () => void;
  /** Bumped when the agent changed files or a deploy finished; reloads an open preview. */
  refreshSignal?: number;
}) {
  const latest = runs[0] ?? null;

  if (!runsLoaded) return <p className="p-4 text-sm text-muted">Loading…</p>;

  if (!latest) {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto">
        <EmptyState
          title="Not deployed yet"
          action={
            <button className="btn-primary" onClick={onDeploy}>
              Deploy
            </button>
          }
        >
          Deploying builds and runs the project so you can see it here.
        </EmptyState>
      </div>
    );
  }

  const label =
    latest.status === "running" ? PHASE_LABEL[latest.phase] : latest.status === "success" ? "Deployed" : "Last deploy failed";
  const dot = latest.status === "running" ? "bg-warn" : latest.status === "success" ? "bg-ok" : "bg-brand";

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-3 desk:p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm">
        <span className={`inline-block w-2 h-2 rounded-full ${dot}`} aria-hidden="true" />
        <span className="flex-1">{label}</span>
        <button className="btn-default text-xs" onClick={onDeploy}>
          {latest.status === "failed" ? "View details" : "Deploy"}
        </button>
      </div>
      <PreviewPanel project={project} refreshSignal={refreshSignal} />
      <PreviewNotices project={project} onOpenSecrets={onOpenSecrets} />
    </div>
  );
}
