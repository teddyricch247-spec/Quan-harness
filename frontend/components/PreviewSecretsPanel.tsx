"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { PreviewRestartResult, PreviewSecret, Project } from "@/lib/types";

// §23.8's Secrets panel: key/value pairs, ONE set, preview only.
//
// Not the same thing as the project secrets in Settings. Those are the ones the
// coding agent can use in its shell commands (and whose names it sees). These are the
// opposite on purpose: they go only to the running preview, and the agent can neither
// see nor use them — they are never part of the conversation. That distinction is
// stated on screen because people will otherwise reasonably wonder which to use.
//
// This panel never displays a value after it's saved (the API doesn't return one); at
// most a short hint of the ending, for values long enough that it doesn't give much away.
export default function PreviewSecretsPanel({ project }: { project: Project }) {
  const [secrets, setSecrets] = useState<PreviewSecret[]>([]);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [needsRestart, setNeedsRestart] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [restartNote, setRestartNote] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<PreviewSecret[]>(`/projects/${project.id}/preview/secrets`)
      .then(setSecrets)
      .catch((e: ApiError) => setError(e.message));
  }, [project.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function save() {
    setSaving(true);
    setError(null);
    setRestartNote(null);
    try {
      await apiFetch<PreviewSecret>(`/projects/${project.id}/preview/secrets`, {
        method: "PUT",
        body: JSON.stringify({ name: name.trim(), value }),
      });
      setName("");
      setValue("");
      setNeedsRestart(true);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await apiFetch(`/projects/${project.id}/preview/secrets/${id}`, { method: "DELETE" });
      setConfirmDeleteId(null);
      setNeedsRestart(true);
      load();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  // Nothing is applied to a running app on its own (§23.8: opt-in). Saving only stores the
  // value; this is the explicit step that gives the app its new environment.
  async function restart() {
    setRestarting(true);
    setError(null);
    setRestartNote(null);
    try {
      const out = await apiFetch<PreviewRestartResult>(`/projects/${project.id}/preview/restart`, { method: "POST" });
      const failed = out.results.filter((r) => !r.started);
      setRestartNote(failed.length === 0 ? "The app was restarted with these secrets." : `Couldn't restart: ${failed.map((f) => f.target).join(", ")}.`);
      if (failed.length === 0) setNeedsRestart(false);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setRestarting(false);
    }
  }

  return (
    <div id="preview-secrets" className="card">
      <p className="text-sm font-medium mb-1">Preview secrets</p>
      <p className="text-xs text-muted mb-3">
        API keys and tokens your app needs to run in the preview — the things that usually live in a .env file that isn&apos;t in the
        repository. They&apos;re given only to the running preview. The coding agent can&apos;t see or use them, and they&apos;re never part
        of the conversation. (These are separate from the project secrets in Settings, which the agent <em>can</em> use in commands.)
      </p>

      {error && <p className="text-sm text-accent mb-2">{error}</p>}

      {secrets.length === 0 ? (
        <p className="text-sm text-muted mb-3">None set.</p>
      ) : (
        <ul className="mb-3 divide-y">
          {secrets.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-1.5 text-sm">
              <span>
                <code className="mono">{s.name}</code>
                <span className="text-muted text-xs ml-2">{s.value_hint ? `ends in ${s.value_hint}` : "value hidden"}</span>
              </span>
              {confirmDeleteId === s.id ? (
                <span className="text-xs">
                  Remove?{" "}
                  <button className="underline text-accent" onClick={() => remove(s.id)}>
                    Yes
                  </button>{" "}
                  ·{" "}
                  <button className="underline" onClick={() => setConfirmDeleteId(null)}>
                    No
                  </button>
                </span>
              ) : (
                <button className="text-xs underline text-muted" onClick={() => setConfirmDeleteId(s.id)}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]">
        <input
          className="input mono"
          placeholder="NAME (e.g. STRIPE_SECRET_KEY)"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <input
          className="input mono"
          type="password"
          placeholder="Value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="new-password"
          spellCheck={false}
        />
        <button className="btn-primary text-sm" onClick={save} disabled={saving || !name.trim() || !value}>
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      <p className="text-xs text-muted mt-2">Saving a name that already exists replaces its value.</p>

      {needsRestart && (
        <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="mb-2">Changes take effect when the app restarts — nothing is applied to a running app on its own.</p>
          <button className="btn-default text-sm" onClick={restart} disabled={restarting}>
            {restarting ? "Restarting…" : "Restart app now"}
          </button>
        </div>
      )}
      {restartNote && <p className="text-xs text-muted mt-2">{restartNote}</p>}
    </div>
  );
}
