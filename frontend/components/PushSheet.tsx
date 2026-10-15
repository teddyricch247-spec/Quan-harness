"use client";

import { useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Project, PushResult } from "@/lib/types";
import ErrorBanner from "./ErrorBanner";
import Sheet from "./Sheet";

/** ⋯ → Push. Converted from WorkspaceSyncPanel (Phase Convert, C7); the call and its result are unchanged. */
export default function PushSheet({
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PushResult | null>(null);

  async function push() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await apiFetch<PushResult>(`/projects/${project.id}/push`, { method: "POST", body: "{}" }));
      onDone();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Push">
      <div className="p-4 space-y-3">
        <p className="text-sm text-muted">
          Sends the workspace’s work to GitHub{project.github_repo ? <> (<span className="mono">{project.github_repo}</span>)</> : <> — a repository is created and linked first if this project has none yet</>}.
        </p>
        <ErrorBanner message={error} />
        {result && (
          <p className="text-sm">
            Pushed to <span className="mono">{result.full_name}</span>@<span className="mono">{result.branch}</span> ({result.commit_sha.slice(0, 7)}).
            {result.pull_request_url && (
              <>
                {" "}
                <a className="underline" href={result.pull_request_url} target="_blank" rel="noreferrer">
                  View pull request
                </a>
              </>
            )}
          </p>
        )}
        <button className="btn-primary w-full disabled:opacity-40" disabled={busy} onClick={push}>
          {busy ? "Pushing…" : "Push"}
        </button>
      </div>
    </Sheet>
  );
}
