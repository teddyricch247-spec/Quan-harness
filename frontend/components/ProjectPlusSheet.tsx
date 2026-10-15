"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { McpServer } from "@/lib/types";
import ErrorBanner from "./ErrorBanner";
import { ImageIcon } from "./icons";
import Sheet from "./Sheet";

/**
 * The workspace's "+": *this project* (C4: "Home's + is project setup … The workspace + is this
 * project. Repo options never appear inside a project."). Connector switches write the project's
 * grants — `connectors-access`, the same many-to-many toggle as Project settings (§9.3), taking
 * effect on the project's next session. "Add an image" (Phase 6.1) opens the chat pane's picture
 * picker; the pictures wait in the message box and go with the next message.
 */
export default function ProjectPlusSheet({
  open,
  onClose,
  projectId,
  connectors,
  onAddImage,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  connectors: McpServer[];
  /** Opens the chat pane's picture picker. Omitted → the row is not shown. */
  onAddImage?: () => void;
}) {
  const [granted, setGranted] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    apiFetch<string[]>(`/projects/${projectId}/connectors-access`)
      .then(setGranted)
      .catch((e: ApiError) => setError(e.message));
  }, [projectId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function toggle(id: string) {
    if (granted === null) return;
    const next = granted.includes(id) ? granted.filter((g) => g !== id) : [...granted, id];
    setBusyId(id);
    setError(null);
    try {
      setGranted(await apiFetch<string[]>(`/projects/${projectId}/connectors-access`, { method: "PUT", body: JSON.stringify({ connector_ids: next }) }));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusyId(null);
    }
  }

  const usable = connectors.filter((c) => c.enabled);

  return (
    <Sheet open={open} onClose={onClose} title="This project">
      {onAddImage && (
        <button type="button" className="row w-full text-left" onClick={onAddImage}>
          <ImageIcon className="w-5 h-5 flex-none" />
          <span className="flex-1">Add an image</span>
        </button>
      )}
      <div className="px-4 pt-3">
        <ErrorBanner message={error} />
        <p className="text-sm text-muted">Connectors the agent may use in this project. Changes apply from the next session.</p>
      </div>
      {usable.length === 0 ? (
        <Link href="/connections/connectors" className="row text-sm mt-2">
          No connectors yet — add one in Settings
        </Link>
      ) : (
        <ul className="mt-2">
          {usable.map((c) => (
            <li key={c.id}>
              <label className="row cursor-pointer">
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{c.name}</span>
                  <span className="block truncate text-xs text-muted mono">{c.url}</span>
                </span>
                <input
                  type="checkbox"
                  role="switch"
                  checked={granted?.includes(c.id) ?? false}
                  disabled={granted === null || busyId !== null}
                  aria-label={`Give this project access to ${c.name}`}
                  onChange={() => toggle(c.id)}
                />
              </label>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}
