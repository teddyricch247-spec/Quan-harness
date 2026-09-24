"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import WorkspaceShell from "@/components/WorkspaceShell";
import WorkspaceSyncPanel from "@/components/WorkspaceSyncPanel";
import { apiFetch, ApiError } from "@/lib/api";
import { Project } from "@/lib/types";

function ProjectWorkspace() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Phase 4.4: a one-time notice from the New Project wizard when the
  // 'import' mode's automatic first Pull failed (see routers/projects.py's
  // create_project and app/projects/new/page.tsx's execute()) — the project
  // itself is real either way, this just says the workspace still needs a
  // manual Pull below. Dismissible; not re-fetched from the project itself,
  // since GET /projects/{id} never carries this field (see ProjectOut's own
  // comment) — it only ever arrives once, via the redirect that brought the
  // person here.
  const [importWarning, setImportWarning] = useState<string | null>(searchParams.get("import_warning"));

  useEffect(() => {
    apiFetch<Project>(`/projects/${params.id}`)
      .then(setProject)
      .catch((e: ApiError) => setError(e.message));
  }, [params.id]);

  if (error) return <ErrorBanner message={error} />;
  if (!project) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-lg font-semibold">{project.name}</h1>
        <Link href={`/projects/${project.id}/settings`} className="btn-default text-sm">
          Settings
        </Link>
      </div>
      <p className="text-sm text-muted mono mb-6">{project.github_repo ?? "not linked yet"}</p>

      {importWarning && (
        <div className="border border-amber-400 bg-amber-50 rounded p-3 mb-4 text-sm">
          <p className="mb-2">
            The repository was imported and linked, but pulling its content into the workspace
            failed: <span className="mono">{importWarning}</span> Use the Pull button in
            Workspace &amp; sync below to try again once that's resolved.
          </p>
          <button className="btn-default text-xs" onClick={() => setImportWarning(null)}>
            Dismiss
          </button>
        </div>
      )}

      {/* §11.2's two-pane Workspace layout, stood up now per the implementation order's
          "mobile single-column collapse behavior, from the start" — even though neither
          pane has real content yet. The turn loop (chat/plan/transcript) is Phase 3; Live
          Preview is Phase 5 (§23). Building the responsive shell now means neither phase
          has to revisit this layout, only fill in what each pane renders. */}
      <WorkspaceShell
        leftLabel="Chat"
        rightLabel="Preview"
        left={
          <div className="card">
            <p className="text-sm font-medium mb-1">Plan &amp; transcript — not built yet</p>
            <p className="text-sm text-muted">
              The pinned plan panel, tool-call transcript, and inline approval cards
              (§11.2) render here once the turn loop exists (Phase 3). This project's
              data model, credential selection, and connector grants are live in the
              meantime.
            </p>
          </div>
        }
        right={
          <div className="card">
            <p className="text-sm font-medium mb-1">Live Preview — not built yet</p>
            <p className="text-sm text-muted">
              The proxied iframe preview (§11.2, §23) lands with the Deploy Pipeline in Phase 5.
              Push, Pull, and checkpoints are real now, below — they were originally guessed to
              land alongside Live Preview in Phase 1's placeholder text here, but §23.3's
              implementation order actually puts them in Phase 2.
            </p>
          </div>
        }
      />

      <div className="mt-4">
        <WorkspaceSyncPanel project={project} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 mt-4">
        <Link href={`/projects/${project.id}/sessions`} className="card hover:border-ink">
          <p className="font-medium text-sm">Sessions</p>
          <p className="text-sm text-muted">View and create session records for this project.</p>
        </Link>
        <Link href={`/projects/${project.id}/settings`} className="card hover:border-ink">
          <p className="font-medium text-sm">Settings</p>
          <p className="text-sm text-muted">
            Credential selection, connector grants, test command, and project deletion.
          </p>
        </Link>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
          <ProjectWorkspace />
        </Suspense>
      </main>
    </AuthGuard>
  );
}
