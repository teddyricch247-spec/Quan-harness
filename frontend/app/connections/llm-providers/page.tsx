"use client";

import { useEffect, useMemo, useState } from "react";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import {
  LlmCredential,
  LlmModel,
  LlmProbeResult,
  LlmProviderPreset,
  LlmQuickModel,
  ReasoningConfig,
  ReasoningOptions,
} from "@/lib/types";

const MAX_RENDERED_MODELS = 200;

function formatContext(n: number | null): string | null {
  if (!n) return null;
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M ctx` : `${Math.round(n / 1000)}k ctx`;
}

const EFFORT_LABELS: Record<string, string> = {
  none: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Max",
};
const DEFAULT_VALUE = "__default";
const BUDGET_VALUE = "__budget";

function describeReasoning(r: ReasoningConfig | undefined): string {
  if (!r) return "model default";
  const parts: string[] = [];
  if (r.effort) parts.push(EFFORT_LABELS[r.effort] ?? r.effort);
  else if (r.max_tokens) parts.push(`${r.max_tokens.toLocaleString()} token budget`);
  else parts.push("model default");
  if (r.show === false) parts.push("hidden");
  return parts.join(" · ");
}

// The model's own thinking controls: its native levels (so a model that has no "Max" doesn't
// show one), an optional raw token budget, and whether the thinking text is returned at all.
// Everything unset means "the model's default" — nothing is sent to the provider for it.
function ThinkingControls({
  options,
  value,
  onChange,
}: {
  options: ReasoningOptions;
  value: ReasoningConfig;
  onChange: (next: ReasoningConfig) => void;
}) {
  const mode = value.effort ? value.effort : value.max_tokens ? BUDGET_VALUE : DEFAULT_VALUE;
  return (
    <div className="space-y-2">
      <div>
        <label className="label">Thinking</label>
        <select
          className="input"
          value={mode}
          onChange={(e) => {
            const v = e.target.value;
            const show = value.show;
            if (v === DEFAULT_VALUE) onChange({ show });
            else if (v === BUDGET_VALUE) onChange({ max_tokens: 8000, show });
            else onChange({ effort: v, show });
          }}
        >
          <option value={DEFAULT_VALUE}>Model default</option>
          {options.efforts.map((e) => (
            <option key={e} value={e}>
              {EFFORT_LABELS[e] ?? e}
            </option>
          ))}
          {options.supports_budget && <option value={BUDGET_VALUE}>Custom token budget…</option>}
        </select>
      </div>
      {mode === BUDGET_VALUE && (
        <div>
          <label className="label">Thinking token budget</label>
          <input
            className="input mono"
            type="number"
            min={1024}
            max={32768}
            step={512}
            value={value.max_tokens ?? 8000}
            onChange={(e) => onChange({ max_tokens: Number(e.target.value) || 1024, show: value.show })}
          />
          <p className="text-xs text-muted mt-1">1,024 – 32,768. Counts toward the model's output limit.</p>
        </div>
      )}
      <label className="flex items-center gap-2 text-xs text-muted">
        <input
          type="checkbox"
          checked={value.show !== false}
          onChange={(e) => onChange({ ...value, show: e.target.checked })}
        />
        Show the model's thinking in sessions
      </label>
    </div>
  );
}

function without<T>(obj: Record<string, T>, key: string): Record<string, T> {
  const next = { ...obj };
  delete next[key];
  return next;
}

// A config with nothing set is sent as-is: the backend stores {} for it (= model default).
function normalizeReasoning(r: ReasoningConfig): ReasoningConfig {
  return { effort: r.effort ?? null, max_tokens: r.effort ? null : r.max_tokens ?? null, show: r.show !== false };
}

function LlmProvidersManager() {
  const [creds, setCreds] = useState<LlmCredential[] | null>(null);
  const [presets, setPresets] = useState<LlmProviderPreset[]>([]);
  const [quickModels, setQuickModels] = useState<LlmQuickModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // --- connect flow ---
  const [presetId, setPresetId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [probe, setProbe] = useState<LlmProbeResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [model, setModel] = useState("");
  const [manualModel, setManualModel] = useState(false);
  const [filter, setFilter] = useState("");
  const [toolsOnly, setToolsOnly] = useState(true);
  const [label, setLabel] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  // One-tap connection (e.g. Ling 3.1 Flash): provider + model are preset, only the key is typed.
  const [quick, setQuick] = useState<LlmQuickModel | null>(null);
  const [reasoning, setReasoning] = useState<ReasoningConfig>({});

  // --- thinking edits on saved credentials, keyed by credential id (absent = not editing) ---
  const [editing, setEditing] = useState<Record<string, ReasoningConfig>>({});

  // --- saved-credential test results, keyed by credential id ---
  const [tests, setTests] = useState<Record<string, { pending: boolean; result?: LlmProbeResult }>>({});

  const preset = presets.find((p) => p.id === presetId) ?? null;

  function load() {
    apiFetch<LlmCredential[]>("/connections/llm-credentials")
      .then(setCreds)
      .catch((e: ApiError) => setError(e.message));
  }
  useEffect(load, []);
  useEffect(() => {
    apiFetch<LlmProviderPreset[]>("/connections/llm-credentials/providers")
      .then(setPresets)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  useEffect(() => {
    apiFetch<LlmQuickModel[]>("/connections/llm-credentials/quick-models")
      .then(setQuickModels)
      .catch(() => setQuickModels([])); // a convenience list — never worth an error banner
  }, []);

  const providerName = (id: string) => presets.find((p) => p.id === id)?.name ?? id;

  function resetForm() {
    setPresetId(null);
    setApiKey("");
    setBaseUrl("");
    setProbe(null);
    setModel("");
    setManualModel(false);
    setFilter("");
    setToolsOnly(true);
    setLabel("");
    setIsDefault(false);
    setQuick(null);
    setReasoning({});
  }

  function choosePreset(p: LlmProviderPreset) {
    resetForm();
    setPresetId(p.id);
    setLabel(p.name);
  }

  function chooseQuick(q: LlmQuickModel) {
    resetForm();
    setPresetId(q.provider);
    setQuick(q);
    setModel(q.model);
    setLabel(q.name);
  }

  // The thinking levels offered for the model currently chosen: a model with its own profile
  // (a quick model, matched by id even if picked from the list) first, else the provider's
  // generic levels — and none at all if the provider said this model doesn't think.
  const chosenQuick = quick ?? quickModels.find((q) => q.provider === presetId && q.model === model.trim()) ?? null;
  const picked = probe?.models.find((m) => m.id === model.trim());
  const reasoningOptions: ReasoningOptions | null =
    chosenQuick?.reasoning ?? (picked?.supports_reasoning === false ? null : preset?.reasoning ?? null);

  // A probe result describes the key + URL it was run with — drop it as soon as either changes.
  function onKeyChange(v: string) {
    setApiKey(v);
    setProbe(null);
    setModel(quick ? quick.model : ""); // a one-tap model is fixed; only a picked one is dropped
  }
  function onBaseUrlChange(v: string) {
    setBaseUrl(v);
    setProbe(null);
    setModel(quick ? quick.model : "");
  }

  async function runProbe() {
    if (!preset) return;
    setProbing(true);
    setError(null);
    setProbe(null);
    try {
      const result = await apiFetch<LlmProbeResult>("/connections/llm-credentials/probe", {
        method: "POST",
        body: JSON.stringify({
          provider: preset.id,
          api_key: apiKey.trim(),
          base_url: preset.requires_base_url ? baseUrl.trim() : undefined,
        }),
      });
      setProbe(result);
      // Unknown/failed list → straight to manual entry so the person is never stuck.
      setManualModel(result.models.length === 0);
      // "Tool-capable only" is only a meaningful default if the provider reported any capability data.
      setToolsOnly(result.models.some((m) => m.supports_tools === true));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setProbing(false);
    }
  }

  const visibleModels = useMemo(() => {
    if (!probe) return [] as LlmModel[];
    const q = filter.trim().toLowerCase();
    return probe.models.filter(
      (m) =>
        (!toolsOnly || m.supports_tools !== false) &&
        (!q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
    );
  }, [probe, filter, toolsOnly]);

  const hasToolData = !!probe?.models.some((m) => m.supports_tools !== null);
  const probeBlocksConnect = probe?.status === "invalid_key" || probe?.status === "bad_request";
  const canConnect =
    !!preset &&
    !busy &&
    !!apiKey.trim() &&
    !!model.trim() &&
    !!label.trim() &&
    (!preset.requires_base_url || !!baseUrl.trim()) &&
    !probeBlocksConnect;

  const prefixWarning =
    preset?.key_prefix_hint && apiKey.trim() && !apiKey.trim().startsWith(preset.key_prefix_hint)
      ? `${preset.name} keys usually start with "${preset.key_prefix_hint}" — double-check you pasted the right one.`
      : null;

  async function create() {
    if (!preset) return;
    setBusy(true);
    setError(null);
    try {
      await apiFetch("/connections/llm-credentials", {
        method: "POST",
        body: JSON.stringify({
          label: label.trim(),
          provider: preset.id,
          model: model.trim(),
          api_key: apiKey.trim(),
          base_url: preset.requires_base_url ? baseUrl.trim() : undefined,
          is_default: isDefault,
          // Only sent when the person changed something, so an untouched form stays exactly as before.
          reasoning:
            reasoningOptions && (reasoning.effort || reasoning.max_tokens || reasoning.show === false)
              ? normalizeReasoning(reasoning)
              : undefined,
        }),
      });
      resetForm();
      setShowForm(false);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function testSaved(id: string) {
    setTests((t) => ({ ...t, [id]: { pending: true } }));
    try {
      const result = await apiFetch<LlmProbeResult>(`/connections/llm-credentials/${id}/probe`, { method: "POST" });
      setTests((t) => ({ ...t, [id]: { pending: false, result } }));
    } catch (e) {
      setTests((t) => ({
        ...t,
        [id]: { pending: false, result: { status: "unreachable", message: (e as ApiError).message, models: [] } },
      }));
    }
  }

  async function saveReasoning(id: string) {
    const next = editing[id];
    if (!next) return;
    setError(null);
    try {
      await apiFetch(`/connections/llm-credentials/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ reasoning: normalizeReasoning(next) }),
      });
      setEditing((e) => without(e, id));
      load();
    } catch (e) {
      setError((e as ApiError).message);
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
      body: JSON.stringify({ api_key: newKey.trim() }),
    });
    load();
    testSaved(id); // a rotated key is worth checking immediately
  }

  async function remove(id: string) {
    if (!window.confirm("Disconnect this credential? Any project using it as its selection will break.")) return;
    await apiFetch(`/connections/llm-credentials/${id}`, { method: "DELETE" });
    load();
  }

  const probeTone = (r: LlmProbeResult) =>
    r.status === "ok" ? "text-ok" : r.status === "invalid_key" || r.status === "bad_request" ? "text-accent" : "text-muted";

  const probeSummary = (r: LlmProbeResult) =>
    r.status === "ok" ? `Key works · ${r.models.length} models` : r.message ?? r.status;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-semibold">LLM Providers</h1>
        <button
          className="btn-primary"
          onClick={() => {
            if (showForm) resetForm();
            setShowForm((s) => !s);
          }}
        >
          {showForm ? "Cancel" : "Connect a credential"}
        </button>
      </div>
      <ErrorBanner message={error} />

      {showForm && !preset && (
        <div className="mb-4">
          {quickModels.length > 0 && (
            <div className="mb-4">
              <p className="text-sm text-muted mb-2">One tap — paste only your key.</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {quickModels.map((q) => (
                  <button key={q.id} className="card text-left p-3 hover:bg-paper" onClick={() => chooseQuick(q)}>
                    <p className="text-sm font-medium">
                      {q.name}
                      {q.free && <span className="text-xs text-ok ml-1">(free)</span>}
                    </p>
                    <p className="text-xs text-muted mt-1">{q.blurb}</p>
                    <p className="text-xs text-muted mt-1">via {providerName(q.provider)}</p>
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="text-sm text-muted mb-2">Or pick where your key is from.</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {presets.map((p) => (
              <button
                key={p.id}
                className="card text-left p-3 hover:bg-paper"
                onClick={() => choosePreset(p)}
              >
                <p className="text-sm font-medium">
                  {p.name}
                  {p.recommended && <span className="text-xs text-ok ml-1">(easiest)</span>}
                </p>
                <p className="text-xs text-muted mt-1">{p.blurb}</p>
              </button>
            ))}
          </div>
        </div>
      )}

      {showForm && preset && (
        <div className="card mb-4 space-y-3 max-w-md">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium">{quick ? quick.name : preset.name}</p>
            <button className="text-xs text-muted underline" onClick={resetForm}>
              {quick ? "Back" : "Change provider"}
            </button>
          </div>
          {quick && (
            <div className="space-y-1">
              <p className="text-xs text-muted mono break-all">
                {preset.name} · {quick.model}
              </p>
              {quick.note && <p className="text-xs text-muted">{quick.note}</p>}
            </div>
          )}

          {preset.requires_base_url && (
            <div>
              <label className="label">Base URL</label>
              <input
                className="input"
                placeholder="https://your-endpoint.example.com/v1"
                value={baseUrl}
                onChange={(e) => onBaseUrlChange(e.target.value)}
              />
              <p className="text-xs text-muted mt-1">Must be publicly reachable — this runs from the cloud, not your device.</p>
            </div>
          )}

          <div>
            <div className="flex items-center justify-between">
              <label className="label">API key</label>
              {preset.key_url && (
                <a className="text-xs text-muted underline mb-1" href={preset.key_url} target="_blank" rel="noreferrer">
                  Get a key ↗
                </a>
              )}
            </div>
            <input
              className="input"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => onKeyChange(e.target.value)}
            />
            {prefixWarning && <p className="text-xs text-accent mt-1">{prefixWarning}</p>}
          </div>

          <button
            className="btn-default w-full"
            disabled={probing || !apiKey.trim() || (preset.requires_base_url && !baseUrl.trim())}
            onClick={runProbe}
          >
            {probing ? "Checking…" : "Verify key & load models"}
          </button>

          {probe && <p className={`text-sm ${probeTone(probe)}`}>{probeSummary(probe)}</p>}

          {probe && !probeBlocksConnect && !quick && (
            <div className="space-y-2">
              <label className="label">Model</label>

              {!manualModel && probe.models.length > 0 && (
                <>
                  <input
                    className="input"
                    placeholder="Search models…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                  {hasToolData && (
                    <label className="flex items-center gap-2 text-xs text-muted">
                      <input type="checkbox" checked={toolsOnly} onChange={(e) => setToolsOnly(e.target.checked)} />
                      Hide models that can't use tools (this agent needs tool calling)
                    </label>
                  )}
                  <div className="max-h-64 overflow-y-auto border border-line rounded-md divide-y divide-line">
                    {visibleModels.slice(0, MAX_RENDERED_MODELS).map((m) => (
                      <button
                        key={m.id}
                        className={`w-full text-left px-3 py-2 ${model === m.id ? "bg-paper" : "bg-white"} hover:bg-paper`}
                        onClick={() => setModel(m.id)}
                      >
                        <p className="text-sm mono break-all">
                          {m.id}
                          {model === m.id && <span className="text-ok ml-1">✓</span>}
                        </p>
                        <p className="text-xs text-muted">
                          {[m.name !== m.id ? m.name : null, formatContext(m.context_length)]
                            .filter(Boolean)
                            .join(" · ")}
                          {m.supports_tools === false && <span className="text-accent"> no tool support</span>}
                        </p>
                      </button>
                    ))}
                    {visibleModels.length === 0 && <p className="text-xs text-muted px-3 py-2">No models match.</p>}
                    {visibleModels.length > MAX_RENDERED_MODELS && (
                      <p className="text-xs text-muted px-3 py-2">
                        Showing {MAX_RENDERED_MODELS} of {visibleModels.length} — search to narrow down.
                      </p>
                    )}
                  </div>
                </>
              )}

              {(manualModel || probe.models.length === 0) && (
                <input
                  className="input mono"
                  placeholder={preset.model_placeholder}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                />
              )}

              {probe.models.length > 0 && (
                <button className="text-xs text-muted underline" onClick={() => setManualModel((m) => !m)}>
                  {manualModel ? "Pick from the list instead" : "Enter a model ID manually"}
                </button>
              )}
            </div>
          )}

          {!probe && !quick && (
            <div className="space-y-2">
              <p className="text-xs text-muted">
                Verifying first catches a wrong key before your first agent turn does — and lets you pick a model instead
                of typing its ID. Or skip it and type the model ID:
              </p>
              <input
                className="input mono"
                placeholder={preset.model_placeholder}
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </div>
          )}

          {reasoningOptions && model.trim() && (
            <ThinkingControls options={reasoningOptions} value={reasoning} onChange={setReasoning} />
          )}

          <div>
            <label className="label">Label</label>
            <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
            Set as account default
          </label>

          <button className="btn-primary w-full" disabled={!canConnect} onClick={create}>
            {busy ? "Connecting…" : "Connect"}
          </button>
        </div>
      )}

      <div className="space-y-2">
        {creds?.map((c) => {
          const t = tests[c.id];
          return (
            <div key={c.id} className="card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium text-sm">
                    {c.label} {c.is_default && <span className="text-xs text-ok ml-1">(default)</span>}
                  </p>
                  <p className="text-xs text-muted mono break-all">
                    {providerName(c.provider)} · {c.model} · key ending {c.api_key_last_four}
                  </p>
                  {c.reasoning_options && (
                    <p className="text-xs text-muted mt-1">Thinking: {describeReasoning(c.reasoning)}</p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-default text-xs py-1" disabled={t?.pending} onClick={() => testSaved(c.id)}>
                    {t?.pending ? "Testing…" : "Test"}
                  </button>
                  {!c.is_default && (
                    <button className="btn-default text-xs py-1" onClick={() => setDefault(c.id)}>
                      Set default
                    </button>
                  )}
                  {c.reasoning_options && (
                    <button
                      className="btn-default text-xs py-1"
                      onClick={() =>
                        setEditing((e) => (c.id in e ? without(e, c.id) : { ...e, [c.id]: { ...c.reasoning } }))
                      }
                    >
                      Thinking
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
              {c.reasoning_options && c.id in editing && (
                <div className="mt-3 max-w-sm space-y-2">
                  <ThinkingControls
                    options={c.reasoning_options}
                    value={editing[c.id]}
                    onChange={(next) => setEditing((e) => ({ ...e, [c.id]: next }))}
                  />
                  <button className="btn-primary text-xs py-1" onClick={() => saveReasoning(c.id)}>
                    Save thinking settings
                  </button>
                </div>
              )}
              {t?.result && <p className={`text-xs mt-2 ${probeTone(t.result)}`}>{probeSummary(t.result)}</p>}
            </div>
          );
        })}
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
