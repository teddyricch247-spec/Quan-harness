"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { GithubCredential } from "@/lib/types";

function GithubConnectionManager() {
  const searchParams = useSearchParams();
  const [creds, setCreds] = useState<GithubCredential[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [label, setLabel] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch<GithubCredential[]>("/connections/github-credential")
      .then(setCreds)
      .catch((e: ApiError) => setError(e.message));
  }
  useEffect(load, []);

  useEffect(() => {
    const connected = searchParams.get("connected");
    const err = searchParams.get("error");
    if (connected) setNotice(`Connected as ${connected}.`);
    if (err) setError(err);
  }, [searchParams]);

  async function startOAuth() {
    try {
      const { authorize_url } = await apiFetch<{ authorize_url: string }>(
        "/connections/github-credential/oauth-start"
      );
      window.location.href = authorize_url;
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function addManual() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/connections/github-credential", {
        method: "POST",
        body: JSON.stringify({ label, token, is_default: false }),
      });
      setLabel("");
      setToken("");
      setShowManual(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function rotate(id: string, credentialType: string) {
    if (credentialType !== "pat") {
      window.alert("Only manually-added / OAuth token credentials can be rotated here.");
      return;
    }
    const newToken = window.prompt("Paste the new personal access token:");
    if (!newToken) return;
    try {
      await apiFetch(`/connections/github-credential/${id}/rotate`, {
        method: "PATCH",
        body: JSON.stringify({ token: newToken }),
      });
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("Disconnect this credential? Any project using it for Push/Pull will break until reassigned.")) return;
    await apiFetch(`/connections/github-credential/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <div>
      <h1 className="text-lg font-semibold mb-1">GitHub Connection</h1>
      <p className="text-sm text-muted mb-6">
        This is the sync-only credential Push/Pull use — it's never reachable by the agent, at any tier.
        If you also want the agent itself to have GitHub capability, add GitHub as a connector instead.
      </p>
      <ErrorBanner message={error} />
      {notice && <p className="text-sm text-ok mb-4">{notice}</p>}

      <div className="flex gap-2 mb-4">
        <button className="btn-primary" onClick={startOAuth}>
          Connect GitHub
        </button>
        <button className="btn-default" onClick={() => setShowManual((s) => !s)}>
          {showManual ? "Cancel" : "Add a token manually"}
        </button>
      </div>

      {showManual && (
        <div className="card mb-4 space-y-3 max-w-md">
          <div>
            <label className="label">Label</label>
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div>
            <label className="label">Fine-grained personal access token</label>
            <input className="input" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <button className="btn-primary" disabled={busy} onClick={addManual}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      )}

      <div className="space-y-2">
        {creds?.map((c) => (
          <div key={c.id} className="card flex items-center justify-between">
            <div>
              <p className="font-medium text-sm">
                {c.label} {c.is_default && <span className="text-xs text-ok ml-1">(default)</span>}
              </p>
              <p className="text-xs text-muted mono">
                {c.github_app_account_login ?? "—"} · token ending {c.token_last_four ?? "----"}
              </p>
            </div>
            <div className="flex gap-2">
              <button className="btn-default text-xs py-1" onClick={() => rotate(c.id, c.credential_type)}>
                Rotate
              </button>
              <button className="btn-danger text-xs py-1" onClick={() => remove(c.id)}>
                Disconnect
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function GithubConnectionPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
          <GithubConnectionManager />
        </Suspense>
      </main>
    </AuthGuard>
  );
}
