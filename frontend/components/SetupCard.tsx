"use client";

import type { Project } from "@/lib/types";
import { AlertIcon, CheckIcon, Spinner } from "./icons";

type StepState = "done" | "active" | "failed" | "pending";

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") return <CheckIcon className="w-4 h-4 text-ok" />;
  if (state === "active") return <Spinner className="w-4 h-4 text-muted" />;
  if (state === "failed") return <AlertIcon className="w-4 h-4 text-brand" />;
  return <span className="w-3 h-3 rounded-full border border-line inline-block mx-0.5" />;
}

/**
 * Phase Convert (C4, "What does the user see between pressing send and the first agent output?"):
 * the workspace opens at once with the person's message and this card. Nothing blocks on
 * provisioning. Three steps — project created → workspace starting → agent starting — driven by
 * what the backend reports (`workspace_status`, C8.5), never by timers.
 *
 * `idle` workspace status means nothing is provisioned and nothing is in flight (provisioning is
 * otherwise lazy); the card shows that step as waiting rather than spinning forever.
 */
export default function SetupCard({
  project,
  agentStarted,
  onRetrySetup,
  retrying,
}: {
  project: Project;
  agentStarted: boolean;
  onRetrySetup: () => void;
  retrying: boolean;
}) {
  const ws = project.workspace_status ?? "idle";
  const workspace: StepState = ws === "ready" ? "done" : ws === "failed" ? "failed" : ws === "provisioning" ? "active" : "pending";
  const agent: StepState = agentStarted ? "done" : ws === "failed" ? "pending" : "active";

  return (
    <div className="card" role="status" aria-live="polite">
      <p className="font-semibold text-sm mb-2">Setting up your project</p>
      <ol className="space-y-1.5 text-sm">
        <li className="flex items-center gap-2">
          <StepIcon state="done" /> Project created
        </li>
        <li className="flex items-center gap-2">
          <StepIcon state={workspace} />
          <span className={workspace === "pending" ? "text-muted" : ""}>
            {ws === "failed" ? "Workspace couldn’t start" : ws === "ready" ? "Workspace ready" : ws === "idle" ? "Workspace starts when the agent first needs it" : "Workspace starting"}
          </span>
        </li>
        <li className="flex items-center gap-2">
          <StepIcon state={agent} />
          <span className={agent === "pending" ? "text-muted" : ""}>{agentStarted ? "Agent started" : "Agent starting"}</span>
        </li>
      </ol>
      {ws === "failed" && (
        <div className="mt-3 text-sm">
          {project.workspace_error && <p className="mono text-xs text-muted mb-2 break-words">{project.workspace_error}</p>}
          <button className="btn-default" onClick={onRetrySetup} disabled={retrying}>
            {retrying ? "Retrying…" : "Retry setup"}
          </button>
        </div>
      )}
    </div>
  );
}
