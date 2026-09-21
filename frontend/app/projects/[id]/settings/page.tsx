"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import ConfirmTypedAction from "@/components/ConfirmTypedAction";
import { apiFetch, ApiError } from "@/lib/api";
import {
  GithubCredential,
  LlmCredential,
  McpServer,
  Project,
  ProjectKnowledgeNote,
  ProjectMemory,
  ProjectSecret,
} from "@/lib/types";

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
  const [memory, setMemory] = useState<ProjectMemory | null>(null);
  const [memoryDraft, setMemoryDraft] = useState("");
  const [knowledge, setKnowledge] = useState<ProjectKnowledgeNote[]>([]);
  const [newNoteName, setNewNoteName] = useState("");
  const [newNoteBody, setNewNoteBody] = useState("");
  const [newNoteTriggerType, setNewNoteTriggerType] = useState<"keyword" | "path">("keyword");
  const [newNoteTriggerValue, setNewNoteTriggerValue] = useState("");
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
    apiFetch<ProjectMemory>(`/projects/${params.id}/memory`)
      .then((m) => {
        setMemory(m);
        setMemoryDraft(m.memory_md);
      })
      .catch(() => {});
    apiFetch<ProjectKnowledgeNote[]>(`/projects/${params.id}/knowledge`).then(setKnowledge).catch(() => {});
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

  async function saveMemory() {
    setError(null);
    try {
      const updated = await apiFetch<ProjectMemory>(`/projects/${params.id}/memory`, {
        method: "PUT",
        body: JSON.stringify({ memory_md: memoryDraft }),
      });
      setMemory(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function clearMemory() {
    setError(null);
    try {
      const cleared = await apiFetch<ProjectMemory>(`/projects/${params.id}/memory`, { method: "DELETE" });
      setMemory(cleared);
      setMemoryDraft(cleared.memory_md);
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function addNote() {
    setError(null);
    try {
      await apiFetch<ProjectKnowledgeNote>(`/projects/${params.id}/knowledge`, {
        method: "POST",
        body: JSON.stringify({
          name: newNoteName,
          body: newNoteBody,
          trigger_type: newNoteTriggerType,
          trigger_value: newNoteTriggerValue,
        }),
      });
      setNewNoteName("");
      setNewNoteBody("");
      setNewNoteTriggerValue("");
      loadAll();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  async function deleteNote(id: string) {
    setKnowledge(knowledge.filter((n) => n.id !== id));
    try {
      await apiFetch(`/projects/${params.id}/knowledge/${id}`, { method: "DELETE" });
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

      <section className="card space-y-3">
        <p className="font-medium text-sm">Memory</p>
        <p className="text-sm text-muted">
          What the agent has learned about this project on its own — build quirks, conventions,
          decisions already made — written automatically after a session completes or gets stuck.
          View, edit, or clear it here at any time; the agent has no tool to change this directly.
        </p>
        {memory === null ? (
          <p className="text-sm text-muted">Loading…</p>
        ) : (
          <>
            <textarea
              className="input min-h-[160px] mono"
              value={memoryDraft}
              onChange={(e) => setMemoryDraft(e.target.value)}
              placeholder="Nothing recorded yet."
            />
            <div className="flex gap-2">
              <button className="btn-primary" onClick={saveMemory}>
                Save
              </button>
              <button className="btn-danger" onClick={clearMemory} disabled={!memoryDraft}>
                Clear
              </button>
            </div>
          </>
        )}
      </section>

      <section className="card space-y-3">
        <p className="font-medium text-sm">Project Knowledge</p>
        <p className="text-sm text-muted">
          Short notes you write yourself — pulled into the agent's context only when actually
          relevant, rather than bloating every system prompt. A keyword trigger fires when it
          appears in the task or a file the agent touches; a path trigger fires when the agent
          opens a matching file (glob pattern, e.g. <span className="mono">migrations/*.sql</span>).
          Each note is injected at most once per session.
        </p>
        {knowledge.length > 0 && (
          <ul className="space-y-2">
            {knowledge.map((n) => (
              <li key={n.id} className="border border-line rounded-md p-3 text-sm space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{n.name}</span>
                  <button className="text-accent text-xs" onClick={() => deleteNote(n.id)}>
                    Remove
                  </button>
                </div>
                <p className="text-muted">{n.body}</p>
                <p className="text-xs text-muted mono">
                  {n.trigger_type}: {n.trigger_value}
                </p>
              </li>
            ))}
          </ul>
        )}
        <div className="space-y-2">
          <input
            className="input"
            placeholder="Note name (e.g. Auth wrapper)"
            value={newNoteName}
            onChange={(e) => setNewNoteName(e.target.value)}
          />
          <textarea
            className="input min-h-[80px]"
            placeholder="This project uses a custom auth wrapper, not the framework's default — see auth/README."
            value={newNoteBody}
            onChange={(e) => setNewNoteBody(e.target.value)}
          />
          <div className="flex gap-2">
            <select
              className="input"
              value={newNoteTriggerType}
              onChange={(e) => setNewNoteTriggerType(e.target.value as "keyword" | "path")}
            >
              <option value="keyword">Keyword trigger</option>
              <option value="path">Path trigger (glob)</option>
            </select>
            <input
              className="input"
              placeholder={newNoteTriggerType === "keyword" ? "auth" : "migrations/*.sql"}
              value={newNoteTriggerValue}
              onChange={(e) => setNewNoteTriggerValue(e.target.value)}
            />
          </div>
          <button
            className="btn-default disabled:opacity-40"
            disabled={!newNoteName || !newNoteBody || !newNoteTriggerValue}
            onClick={addNote}
          >
            Add note
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
