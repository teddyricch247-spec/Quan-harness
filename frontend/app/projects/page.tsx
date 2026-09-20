"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { Project } from "@/lib/types";

function billingDot(state: Project["workspace_billing_state"]) {
  const color = state === "running" ? "bg-ok" : state === "warm" ? "bg-yellow-500" : "bg-muted";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} title={state ?? "unknown"} />;
}

function ProjectsList() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Project[]>("/projects")
      .then(setProjects)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold">Projects</h1>
        <Link href="/projects/new" className="btn-primary">
          New Project
        </Link>
      </div>
      <ErrorBanner message={error} />
      {projects === null && !error && <p className="text-sm text-muted">Loading…</p>}
      {projects?.length === 0 && (
        <div className="card text-sm text-muted">
          No projects yet. Start from scratch or import a repository — either way takes under a minute.
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {projects?.map((p) => (
          <Link key={p.id} href={`/projects/${p.id}`} className="card hover:border-ink transition-colors">
            <div className="flex items-start justify-between">
              <span className="font-medium">{p.name}</span>
              {billingDot(p.workspace_billing_state)}
            </div>
            <p className="text-sm text-muted mt-1 mono">{p.github_repo ?? "not linked yet"}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <ProjectsList />
      </main>
    </AuthGuard>
  );
}
