"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Project } from "@/lib/types";
import ErrorBanner from "./ErrorBanner";
import Sheet from "./Sheet";

/** ⋯ → Rename. The name is derived from the first prompt (C8.1); this is where it gets edited (C4). */
export default function RenameSheet({
  open,
  onClose,
  project,
  onRenamed,
}: {
  open: boolean;
  onClose: () => void;
  project: Project;
  onRenamed: (project: Project) => void;
}) {
  const [name, setName] = useState(project.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(project.name);
      setError(null);
    }
  }, [open, project.name]);

  async function save() {
    const next = name.trim();
    if (!next || next === project.name) {
      onClose();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      onRenamed(await apiFetch<Project>(`/projects/${project.id}`, { method: "PATCH", body: JSON.stringify({ name: next }) }));
      onClose();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Rename project">
      <div className="p-4 space-y-3">
        <ErrorBanner message={error} />
        <div>
          <label className="label" htmlFor="rename-project">
            Name
          </label>
          <input
            id="rename-project"
            className="input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !busy && save()}
          />
          <p className="text-xs text-muted mt-1">Deleting the project asks you to type this name.</p>
        </div>
        <button className="btn-primary w-full disabled:opacity-40" disabled={busy || !name.trim()} onClick={save}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </Sheet>
  );
}
