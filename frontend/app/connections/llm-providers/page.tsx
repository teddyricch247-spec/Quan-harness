"use client";

import { useEffect, useState } from "react";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { LlmCredential } from "@/lib/types";

const PROVIDERS = ["anthropic", "openai", "google", "openrouter", "custom"] as const;

function LlmProvidersManager() {
  const [creds, setCreds] = useState<LlmCredential[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [label, setLabel] = useState("");
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]>("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [busy, setBusy] = useState(false);

  function load() {
    apiFetch<LlmCredential[]>("/connections/llm-credentials")
      .then(setCreds)
      .catch((e: ApiError) => setError(e.message));
  }
  useEffect(load, []);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/connections/llm-credentials", {
        method: "POST",
        body: JSON.stringify({
          label,
          provider,
          model,
          api_key: apiKey,
          base_url: provider === "custom" ? baseUrl : undefined,
          is_default: isDefault,
        }),
      });
      setLabel("");
      setModel("");
      setApiKey("");
      setBaseUrl("");
      setIsDefault(false);
      setShowForm(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function setDefault(id: string) {
    await apiFetch(`/connections/llm-credentials/${id}/set-default`, { method: "POST" });
    load();
  }

  async function rotate(id: string) {
    const newKey = window.prompt("Paste the new API key:");
    if (!newKey) return;
    await apiFetch(`/connections/llm-credentials/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ api_key: newKey }),
    });
    load();
  }

  async function remove(id: string) {
    if (!window.confirm("Disconnect this credential? Any project using it as its selection will break.")) return;
    await apiFetch(`/connections/llm-credentials/${id}`, { method: "DELETE" });
    load();
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold">LLM Providers</h1>
        <button className="btn-primary" onClick={() => setShowForm((s) => !s)}>
          {showForm ? "Cancel" : "Connect a credential"}
        </button>
      </div>
      <ErrorBanner message={error} />

      {showForm && (
        <div className="card mb-4 space-y-3 max-w-md">
          <div>
            <label className="label">Label</label>
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div>
            <label className="label">Provider</label>
            <select className="input" value={provider} onChange={(e) => setProvider(e.target.value as any)}>
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Model</label>
            <input className="input" value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
          {provider === "custom" && (
            <div>
              <label className="label">Base URL</label>
              <input className="input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </div>
          )}
          <div>
            <label className="label">API key</label>
            <input
              className="input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            Set as account default
          </label>
          <button className="btn-primary" disabled={busy} onClick={create}>
            {busy ? "Connecting…" : "Connect"}
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
                {c.provider}/{c.model} · key ending {c.api_key_last_four}
              </p>
            </div>
            <div className="flex gap-2">
              {!c.is_default && (
                <button className="btn-default text-xs py-1" onClick={() => setDefault(c.id)}>
                  Set default
                </button>
              )}
              <button className="btn-default text-xs py-1" onClick={() => rotate(c.id)}>
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

export default function LlmProvidersPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <LlmProvidersManager />
      </main>
    </AuthGuard>
  );
}
