"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { Guidance, GuidanceOption, PreviewLimitations, PreviewNotification, Project } from "@/lib/types";

// §23.8 — known preview limitations, "surfaced, not silently broken."
//
// NOTIFY-ONLY AND OPT-IN. Nothing in this file changes anything on the person's own
// systems, and nothing is applied automatically. Every button is either a person-
// triggered convenience (copy an address, jump to the Secrets panel) or Dismiss. Where
// a limitation truly can't be fixed from here, it says so (the "can't be fixed from
// here" label), rather than leaving a button that looks like it should work.

const CAN_FIX_LABEL: Record<Guidance["can_fix"], string> = {
  yes: "You can fix this",
  partly: "Partly fixable",
  no: "Can't be fixed from here",
};

const POLL_MS = 10_000;

export default function PreviewNotices({ project, onOpenSecrets }: { project: Project; onOpenSecrets: () => void }) {
  const [notes, setNotes] = useState<PreviewNotification[]>([]);
  const [limits, setLimits] = useState<PreviewLimitations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const loadNotes = useCallback(() => {
    apiFetch<PreviewNotification[]>(`/projects/${project.id}/preview/notifications`)
      .then(setNotes)
      .catch((e: ApiError) => setError(e.message));
  }, [project.id]);

  useEffect(() => {
    loadNotes();
    apiFetch<PreviewLimitations>(`/projects/${project.id}/preview/limitations`)
      .then(setLimits)
      .catch(() => {
        // The standing reference is a nicety; a failure here shouldn't hide the live notices.
      });
    const interval = setInterval(() => {
      if (!document.hidden) loadNotes();
    }, POLL_MS);
    return () => clearInterval(interval);
  }, [loadNotes, project.id]);

  function copy(key: string, text: string) {
    navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 1500);
  }

  async function dismiss(id: string) {
    try {
      await apiFetch(`/projects/${project.id}/preview/notifications/${id}/dismiss`, { method: "POST" });
      loadNotes();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  // A button for an option's `action`. Each one only ever does something the person asked for.
  function actionButton(noteKey: string, option: GuidanceOption) {
    if (option.action === "copy_origin" && limits?.origin) {
      const value = limits.origin;
      return (
        <button className="btn-default text-xs" onClick={() => copy(`${noteKey}:origin`, value)}>
          {copied === `${noteKey}:origin` ? "Copied" : "Copy preview address"}
        </button>
      );
    }
    if (option.action === "copy_ips" && limits && limits.egress_ips.length > 0) {
      return (
        <button className="btn-default text-xs" onClick={() => copy(`${noteKey}:ips`, limits.egress_ips.join(", "))}>
          {copied === `${noteKey}:ips` ? "Copied" : "Copy addresses"}
        </button>
      );
    }
    if (option.action === "open_secrets") {
      return (
        <button className="btn-default text-xs" onClick={onOpenSecrets}>
          Go to Preview secrets
        </button>
      );
    }
    return null;
  }

  return (
    <div className="card">
      <p className="text-sm font-medium mb-1">Preview notices</p>
      <p className="text-xs text-muted mb-3">
        Things that commonly break an app when it runs in a preview. These are only notices — nothing here changes your backend, your
        sign-in provider, your database or your secrets unless you do it yourself.
      </p>

      {error && <p className="text-sm text-accent mb-2">{error}</p>}

      {notes.length === 0 ? (
        <p className="text-sm text-muted mb-3">Nothing to flag right now.</p>
      ) : (
        <ul className="space-y-3 mb-3">
          {notes.map((n) => (
            <li key={n.id} className="border border-amber-400 bg-amber-50 rounded p-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium">{n.title}</p>
                <span className="text-xs text-muted whitespace-nowrap">{CAN_FIX_LABEL[n.guidance.can_fix]}</span>
              </div>
              <p className="mt-1 whitespace-pre-line">{n.body}</p>
              {n.guidance.options.length > 0 && (
                <ul className="mt-2 space-y-2">
                  {n.guidance.options.map((o) => (
                    <li key={o.label} className="text-xs">
                      <p className="font-medium">{o.label}</p>
                      <p className="text-muted mb-1">{o.detail}</p>
                      {actionButton(n.id, o)}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-2 text-right">
                <button className="text-xs underline text-muted" onClick={() => dismiss(n.id)}>
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {limits && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs text-muted">Known preview limitations — what to expect before it happens</summary>
          <ul className="mt-2 space-y-3">
            {limits.guidance.map((g) => (
              <li key={g.kind} className="text-xs">
                <p className="font-medium text-sm">
                  {g.title} <span className="text-muted font-normal">· {CAN_FIX_LABEL[g.can_fix]}</span>
                </p>
                <p className="text-muted">{g.why}</p>
                {g.options.length > 0 && (
                  <ul className="mt-1 list-disc pl-4 space-y-1">
                    {g.options.map((o) => (
                      <li key={o.label}>
                        <span className="font-medium">{o.label}.</span> {o.detail}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
