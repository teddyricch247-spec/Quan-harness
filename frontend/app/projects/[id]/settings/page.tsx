"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import ConfirmTypedAction from "@/components/ConfirmTypedAction";
import { apiFetch, ApiError } from "@/lib/api";
import { GithubCredential, LlmCredential, McpServer, Project, ProjectSecret } from "@/lib/types";

function ProjectSettings() {
  const params = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<Project | null>(null);
  const [githubCreds, setGithubCreds] = useState<GithubCredential[]>([]);
  const [llmCreds, setLlmCreds] = useState<LlmCredential[]>([]);
  const [connectors, setConnectors] = useState<McpServer[]>([]);
  const [grantedIds, setGrantedIds] = useState<string[]>([]);
  const [secrets, setSecrets] = useState<ProjectSecret[]>([]);
  const [newSecretName, setNewSecretName] = useState("");
  const [newSecretValue, setNewSecretValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function loadAll() {
    apiFetch<Project>(`/projects/${params.id}`).then(setProject).catch((e: ApiError) => setError(e.message));
    apiFetch<GithubCredential[]>("/connections/github-credential").then(setGithubCreds).catch(() => {});
    apiFetch<LlmCredential[]>("/connections/llm-credentials").then(setLlmCreds).catch(() => {});
    apiFetch<McpServer[]>("/connections/connectors")
      .then((rows) => setConnectors(rows.filter((r) => r.enabled)))
      .catch(() => {});
    apiFetch<string[]>(`/projects/${params.id}/connectors-access`).then(setGrantedIds).catch(() => {});
    apiFetch<ProjectSecret[]>(`/projects/${params.id}/secrets`).then(setSecrets).catch(() => {});
  }

  useEffect(loadAll, [params.id]);

  async function save(fields: Partial<Project>) {
    setError(null);
    try {
      const updated = await apiFetch<Project>(`/projects/${params.id}`, {
        method: "PATCH",
        body: JSON.stringify(fields),
      });
      setProject(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function toggleConnector(id: string, checked: boolean) {
    const next = checked ? [...grantedIds, id] : grantedIds.filter((g) => g !== id);
    setGrantedIds(next);
    try {
      await apiFetch(`/projects/${params.id}/connectors-access`, {
        method: "PUT",
        body: JSON.stringify({ connector_ids: next }),
      });
    } catch (e) {
      setError((e as ApiError).message);
      loadAll();
    }
  }

  async function deleteProject() {
    await apiFetch(`/projects/${params.id}`, {
      method: "DELETE",
      body: JSON.stringify({ confirmation: project?.name }),
    });
    router.replace("/projects");
  }

  async function addSecret() {
    setError(null);
    try {
      await apiFetch<ProjectSecret>(`/projects/${params.id}/secrets`, {
        method: "POST",
        body: JSON.stringify({ name: newSecretName, value: newSecretValue }),
      });
      setNewSecretName("");
      setNewSecretValue("");
      loadAll();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function deleteSecret(id: string) {
    setSecrets(secrets.filter((s) => s.id !== id));
    try {
      await apiFetch(`/projects/${params.id}/secrets/${id}`, { method: "DELETE" });
    } catch (e) {
      setError((e as ApiError).message);
      loadAll();
    }
  }

  if (!project) return <p className="text-sm text-muted">Loading…</p>;

  return (
    <div className="max-w-lg space-y-6">
      <h1 className="text-lg font-semibold">{project.name} — Settings</h1>
      <ErrorBanner message={error} />
      {saved && <p className="text-sm text-ok">Saved.</p>}

      <section className="card space-y-3">
        <p className="font-medium text-sm">Credentials</p>
        <div>
          <label className="label">LLM credential</label>
          <select
            className="input"
            value={project.llm_credential_id ?? ""}
            onChange={(e) => save({ llm_credential_id: e.target.value || null })}
          >
            <option value="">Use account default</option>
            {llmCreds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label} ({c.provider}/{c.model})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">GitHub credential (sync)</label>
          <select
            className="input"
            value={project.github_credential_id ?? ""}
            onChange={(e) => save({ github_credential_id: e.target.value || null })}
          >
            <option value="">None selected</option>
            {githubCreds.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          {project.github_credential_id && !githubCreds.find((c) => c.id === project.github_credential_id) && (
            <p className="text-xs text-accent mt-1">
              This project's selected GitHub credential no longer exists — Push/Pull will fail until you
              pick a new one.
            </p>
          )}
        </div>
      </section>

      <section className="card space-y-3">
        <p className="font-medium text-sm">Connectors granted to this project</p>
        {connectors.length === 0 && (
          <p className="text-sm text-muted">
            No connectors on your account yet — add one from Connections.
          </p>
        )}
        {connectors.map((c) => (
          <label key={c.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={grantedIds.includes(c.id)}
              onChange={(e) => toggleConnector(c.id, e.target.checked)}
            />
            {c.name}
          </label>
        ))}
      </section>

      <section className="card space-y-3">
        <p className="font-medium text-sm">Agent limits</p>
        <div>
          <label className="label">Test command</label>
          <input
            className="input"
            defaultValue={project.test_command ?? ""}
            onBlur={(e) => save({ test_command: e.target.value || null })}
          />
        </div>
        <div>
          <label className="label">Max turn iterations</label>
          <input
            className="input"
            type="number"
            defaultValue={project.max_turn_iterations}
            onBlur={(e) => save({ max_turn_iterations: Number(e.target.value) })}
          />
        </div>
      </section>

      <section className="card space-y-3">
        <p className="font-medium text-sm">Project secrets</p>
        <p className="text-sm text-muted">
          Available to <span className="mono">execute_bash</span> as environment variables when a
          command references them by name (e.g. <span className="mono">$STRIPE_TEST_KEY</span>) —
          never exposed any other way (§14.3). Distinct from, and not a substitute for, the LLM and
          GitHub credentials above.
        </p>
        {secrets.length > 0 && (
          <ul className="space-y-1">
            {secrets.map((s) => (
              <li key={s.id} className="flex items-center justify-between text-sm">
                <span className="mono">
                  {s.name} <span className="text-muted">…{s.value_last_four}</span>
                </span>
                <button className="text-accent text-xs" onClick={() => deleteSecret(s.id)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input
            className="input"
            placeholder="STRIPE_TEST_KEY"
            value={newSecretName}
            onChange={(e) => setNewSecretName(e.target.value.toUpperCase())}
          />
          <input
            className="input"
            type="password"
            placeholder="value"
            value={newSecretValue}
            onChange={(e) => setNewSecretValue(e.target.value)}
          />
          <button
            className="btn-default disabled:opacity-40"
            disabled={!newSecretName || !newSecretValue}
            onClick={addSecret}
          >
            Add
          </button>
        </div>
      </section>

      <section className="card space-y-3 border-accent/40">
        <p className="font-medium text-sm text-accent">Delete this project</p>
        <p className="text-sm text-muted">
          Removes every session/credential-selection/checkpoint tied to it. Does not touch the actual
          GitHub repository or any underlying compute resource — this system only ever held a reference
          to them.
        </p>
        <ConfirmTypedAction requiredText={project.name} onConfirm={deleteProject} />
      </section>
    </div>
  );
}

export default function ProjectSettingsPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <ProjectSettings />
      </main>
    </AuthGuard>
  );
}
