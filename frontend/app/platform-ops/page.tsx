"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { AuditLogEntry } from "@/lib/types";

const ACTIONS = [
  {
    title: "Connect / disconnect the GitHub sync credential",
    href: "/connections/github",
    note: "Disconnecting a credential a project relies on surfaces plainly on that project's Settings — never a silent fallback.",
  },
  {
    title: "Connect / disconnect an LLM credential",
    href: "/connections/llm-providers",
    note: "Same 'surface plainly, never silently substitute' rule.",
  },
  {
    title: "Connect / review tools / disable a tool / disconnect a connector",
    href: "/connections/connectors",
    note: "Connecting is account-level and grants no project anything by itself.",
  },
  {
    title: "Grant / revoke a project's access to a connector",
    href: "/projects",
    note: "Project-level, from that project's own Settings — independent of the account-level connection.",
  },
  {
    title: "Rotate a credential",
    href: "/connections",
    note: "Overwrites the Vault-stored value; every project using it picks up the new value on its next session automatically.",
  },
  {
    title: "Delete a project",
    href: "/projects",
    note: "From that project's own Settings. Requires typing the project's name to confirm.",
  },
  {
    title: "Delete this account",
    href: "/account",
    note: "Requires typing DELETE to confirm.",
  },
];

function PlatformOps() {
  const [log, setLog] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<AuditLogEntry[]>("/audit-log")
      .then(setLog)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  return (
    <div>
      <h1 className="text-lg font-semibold mb-1">Platform Operations</h1>
      <p className="text-sm text-muted mb-6 max-w-2xl">
        Everything below is a direct, deterministic action you take — never routed through the agent
        loop, never something a session's system prompt has to explain, because there is no tool call
        involved at any point. This is the human-operable fallback that exists independent of whatever
        the agent can or can't do.
      </p>

      <div className="grid gap-3 sm:grid-cols-2 mb-8">
        {ACTIONS.map((a) => (
          <Link key={a.title} href={a.href} className="card hover:border-ink">
            <p className="font-medium text-sm">{a.title}</p>
            <p className="text-xs text-muted mt-1">{a.note}</p>
          </Link>
        ))}
      </div>

      <h2 className="text-sm font-medium text-muted mb-2">Recent activity</h2>
      <ErrorBanner message={error} />
      <div className="space-y-1">
        {log?.length === 0 && <p className="text-sm text-muted">Nothing recorded yet.</p>}
        {log?.map((entry) => (
          <div key={entry.id} className="text-sm flex items-center gap-2 border-b border-line py-1.5 last:border-b-0">
            <span
              className={`text-xs mono px-1.5 py-0.5 rounded ${
                entry.initiated_by === "agent" ? "bg-accent-soft text-accent" : "bg-paper text-muted"
              }`}
            >
              {entry.initiated_by}
            </span>
            <span className="mono text-xs text-muted">{entry.tool}</span>
            <span>{entry.action}</span>
            {!entry.success && <span className="text-accent text-xs">failed</span>}
            <span className="ml-auto text-xs text-muted">{new Date(entry.created_at).toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PlatformOpsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <PlatformOps />
      </main>
    </AuthGuard>
  );
}
