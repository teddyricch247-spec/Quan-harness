"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { Session } from "@/lib/types";

function statusColor(s: Session["status"]) {
  if (s === "completed") return "text-ok";
  if (s === "failed" || s === "stuck") return "text-accent";
  return "text-muted";
}

function SessionsList() {
  const params = useParams<{ id: string }>();
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch<Session[]>(`/projects/${params.id}/sessions`)
      .then(setSessions)
      .catch((e: ApiError) => setError(e.message));
  }

  useEffect(load, [params.id]);

  async function createSession() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/projects/${params.id}/sessions`, {
        method: "POST",
        body: JSON.stringify({ title: title || undefined }),
      });
      setTitle("");
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="text-lg font-semibold mb-4">Sessions</h1>
      <ErrorBanner message={error} />

      <div className="card mb-4 flex gap-2">
        <input
          className="input"
          placeholder="Optional title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button className="btn-primary whitespace-nowrap" disabled={busy} onClick={createSession}>
          New session
        </button>
      </div>

      {sessions?.length === 0 && <p className="text-sm text-muted">No sessions yet.</p>}
      <div className="space-y-2">
        {sessions?.map((s) => (
          <div key={s.id} className="card flex items-center justify-between">
            <div>
              <p className="font-medium text-sm">{s.title ?? "Untitled session"}</p>
              <p className="text-xs text-muted mono">{new Date(s.created_at).toLocaleString()}</p>
            </div>
            <span className={`text-xs font-medium ${statusColor(s.status)}`}>{s.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SessionsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <SessionsList />
      </main>
    </AuthGuard>
  );
}
