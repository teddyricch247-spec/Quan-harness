"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { McpServer } from "@/lib/types";

type AuthMode = "none" | "static_token" | "oauth";
type Permission = "on" | "off" | "ask";

function ToolRow({
  connectorId,
  name,
  description,
  initialPermission,
}: {
  connectorId: string;
  name: string;
  description: string;
  initialPermission: Permission;
}) {
  const [permission, setPermission] = useState<Permission>(initialPermission);

  async function set(p: Permission) {
    setPermission(p);
    await apiFetch(`/connections/connectors/${connectorId}/tools/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ permission_state: p }),
    });
  }

  return (
    <div className="flex items-center justify-between border-t border-line py-2 first:border-t-0">
      <div className="min-w-0 pr-3">
        <p className="text-sm mono truncate">{name}</p>
        {description && <p className="text-xs text-muted truncate">{description}</p>}
      </div>
      <div className="flex gap-1 shrink-0">
        {(["on", "ask", "off"] as Permission[]).map((p) => (
          <button
            key={p}
            onClick={() => set(p)}
            className={`text-xs px-2 py-1 rounded border ${
              permission === p ? "bg-ink text-white border-ink" : "border-line text-muted"
            }`}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}

function ConnectorCard({ connector, onChange }: { connector: McpServer; onChange: () => void }) {
  async function refresh() {
    await apiFetch(`/connections/connectors/${connector.id}/refresh`, { method: "POST" });
    onChange();
  }
  async function confirm() {
    await apiFetch(`/connections/connectors/${connector.id}/confirm`, { method: "POST" });
    onChange();
  }
  async function remove() {
    if (!window.confirm("Disconnect this connector? This removes every project's access to it.")) return;
    await apiFetch(`/connections/connectors/${connector.id}`, { method: "DELETE" });
    onChange();
  }
  async function startOAuth() {
    const { authorize_url } = await apiFetch<{ authorize_url: string }>(
      `/connections/connectors/${connector.id}/oauth-start`
    );
    window.location.href = authorize_url;
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium text-sm">
            {connector.name} {!connector.enabled && <span className="text-xs text-accent ml-1">draft — not active</span>}
          </p>
          <p className="text-xs text-muted mono">{connector.url}</p>
        </div>
        <div className="flex gap-2">
          {connector.auth_mode === "oauth" && !connector.discovered_tools.length && !connector.last_handshake_error && (
            <button className="btn-default text-xs py-1" onClick={startOAuth}>
              Connect via OAuth
            </button>
          )}
          {!connector.enabled && connector.discovered_tools.length > 0 && !connector.last_handshake_error && (
            <button className="btn-primary text-xs py-1" onClick={confirm}>
              Confirm & activate
            </button>
          )}
          <button className="btn-default text-xs py-1" onClick={refresh}>
            Refresh
          </button>
          <button className="btn-danger text-xs py-1" onClick={remove}>
            Disconnect
          </button>
        </div>
      </div>

      {connector.last_handshake_error && (
        <p className="text-xs text-accent mt-2">Handshake failed: {connector.last_handshake_error}</p>
      )}

      {connector.discovered_tools.length > 0 && (
        <div className="mt-3">
          {connector.discovered_tools.map((t) => (
            <ToolRow
              key={t.name}
              connectorId={connector.id}
              name={t.name}
              description={t.description}
              initialPermission={t.permission_state}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectorsManager() {
  const searchParams = useSearchParams();
  const [connectors, setConnectors] = useState<McpServer[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("none");
  const [staticToken, setStaticToken] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch<McpServer[]>("/connections/connectors")
      .then(setConnectors)
      .catch((e: ApiError) => setError(e.message));
  }
  useEffect(load, []);

  useEffect(() => {
    const err = searchParams.get("error");
    if (err) setError(err);
  }, [searchParams]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/connections/connectors", {
        method: "POST",
        body: JSON.stringify({
          name,
          url,
          auth_mode: authMode,
          static_token: authMode === "static_token" ? staticToken : undefined,
        }),
      });
      setName("");
      setUrl("");
      setStaticToken("");
      setAuthMode("none");
      setShowForm(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const drafts = connectors?.filter((c) => !c.enabled) ?? [];
  const active = connectors?.filter((c) => c.enabled) ?? [];

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-lg font-semibold">Connectors</h1>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? "Cancel" : "Add connector"}
        </button>
      </div>
      <p className="text-sm text-muted mb-4">
        The only way the agent reaches anything outside its own workspace — GitHub included. Each tool
        gets its own On/Off/Ask permission; nothing is trusted automatically.
      </p>
      <ErrorBanner message={error} />

      {showForm && (
        <div className="card mb-4 space-y-3 max-w-md">
          <div>
            <label className="label">Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="label">MCP server URL</label>
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/mcp" />
          </div>
          <div>
            <label className="label">Auth mode</label>
            <select className="input" value={authMode} onChange={(e) => setAuthMode(e.target.value as AuthMode)}>
              <option value="none">None</option>
              <option value="static_token">Static token</option>
              <option value="oauth">OAuth</option>
            </select>
          </div>
          {authMode === "static_token" && (
            <div>
              <label className="label">Bearer token</label>
              <input className="input" type="password" value={staticToken} onChange={(e) => setStaticToken(e.target.value)} />
            </div>
          )}
          <button className="btn-primary" disabled={busy || !name || !url} onClick={create}>
            {busy ? "Connecting…" : "Run handshake"}
          </button>
        </div>
      )}

      {drafts.length > 0 && (
        <div className="mb-6">
          <p className="text-sm font-medium text-muted mb-2">Pending review</p>
          <div className="space-y-2">
            {drafts.map((c) => (
              <ConnectorCard key={c.id} connector={c} onChange={load} />
            ))}
          </div>
        </div>
      )}

      <div>
        {active.length === 0 && drafts.length === 0 && (
          <p className="text-sm text-muted">No connectors yet.</p>
        )}
        <div className="space-y-2">
          {active.map((c) => (
            <ConnectorCard key={c.id} connector={c} onChange={load} />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function ConnectorsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
          <ConnectorsManager />
        </Suspense>
      </main>
    </AuthGuard>
  );
}
