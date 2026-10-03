"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import { PreviewRestartResult, PreviewSession, PreviewStatus, Project } from "@/lib/types";

// Phase 5.3 (§23.7). The preview is an iframe on the project's own stable preview
// origin (<subdomain>.<preview domain>); the Sprite's real URL is never exposed to
// the browser, and neither is any credential for it.
//
// BILLING (§23.7 — "the one thing to get right"): a Sprite stays in the billed
// `running` state while a connection to it is open. An iframe with a live
// WebSocket/EventSource in a background tab is exactly that. So the iframe exists
// ONLY while the person can plausibly be looking at it: it is unloaded after the tab
// has been hidden for HIDDEN_UNLOAD_MS (the backend also closes idle sockets after
// 90s and all of them after 15 minutes — this is the other half of the same
// guarantee, not a replacement for it). Status polling only runs while the tab is
// visible, and it only ever reads Sprite *metadata* through our API; it never touches
// the Sprite's URL, so it can't itself keep anything awake.
const STATUS_POLL_MS = 15_000;
const HIDDEN_UNLOAD_MS = 60_000;

// Dot colours match WorkspaceSyncPanel's BILLING_DOT so the same state looks the same on one page.
const BILLING_LABEL: Record<NonNullable<PreviewStatus["billing_state"]>, { text: string; dot: string; hint: string }> = {
  running: { text: "Running", dot: "bg-green-600", hint: "The workspace is awake — this is the only state that's billed." },
  warm: { text: "Idle", dot: "bg-amber-500", hint: "The workspace is paused and not billed. It wakes on the next request." },
  cold: { text: "Asleep", dot: "bg-neutral-400", hint: "The workspace is asleep and not billed. It wakes on the next request." },
};

export default function PreviewPanel({ project }: { project: Project }) {
  const [status, setStatus] = useState<PreviewStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [iframeUrl, setIframeUrl] = useState<string | null>(null);
  const [pausedForIdle, setPausedForIdle] = useState(false);
  const [opening, setOpening] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [restartNote, setRestartNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const hiddenTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The idle timer fires long after the render that created it, so it reads the
  // current URL through a ref rather than a stale closure.
  const iframeUrlRef = useRef<string | null>(null);
  iframeUrlRef.current = iframeUrl;

  const loadStatus = useCallback(() => {
    apiFetch<PreviewStatus>(`/projects/${project.id}/preview`)
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((e: ApiError) => setError(e.message));
  }, [project.id]);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(() => {
      if (!document.hidden) loadStatus();
    }, STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [loadStatus]);

  useEffect(() => {
    function onVisibility() {
      if (document.hidden) {
        if (hiddenTimer.current) clearTimeout(hiddenTimer.current);
        hiddenTimer.current = setTimeout(() => {
          // Unloading the iframe closes every connection the previewed app holds open.
          if (iframeUrlRef.current) {
            setPausedForIdle(true);
            setIframeUrl(null);
          }
        }, HIDDEN_UNLOAD_MS);
      } else {
        if (hiddenTimer.current) clearTimeout(hiddenTimer.current);
        loadStatus();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      if (hiddenTimer.current) clearTimeout(hiddenTimer.current);
    };
  }, [loadStatus]);

  async function openPreview() {
    setOpening(true);
    setError(null);
    setPausedForIdle(false);
    try {
      // Always a fresh session: the URL is single-use and short-lived, so "reload"
      // and "resume" mint a new one rather than reusing an old one.
      const session = await apiFetch<PreviewSession>(`/projects/${project.id}/preview/session`, { method: "POST" });
      setIframeUrl(session.url);
      loadStatus();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setOpening(false);
    }
  }

  async function restart() {
    setRestarting(true);
    setError(null);
    setRestartNote(null);
    try {
      const out = await apiFetch<PreviewRestartResult>(`/projects/${project.id}/preview/restart`, { method: "POST" });
      const failed = out.results.filter((r) => !r.started);
      setRestartNote(
        failed.length === 0
          ? "Restarted with your current preview secrets."
          : `Couldn't restart: ${failed.map((f) => f.target).join(", ")}. Check the deploy log above.`,
      );
      if (iframeUrl && failed.length === 0) await openPreview();
      else loadStatus();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setRestarting(false);
    }
  }

  function copyOrigin() {
    if (!status?.origin) return;
    navigator.clipboard.writeText(status.origin);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const billing = status?.billing_state ? BILLING_LABEL[status.billing_state] : null;

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium">Live Preview</p>
        {billing && (
          <span className="text-xs text-muted" title={billing.hint}>
            <span className={`inline-block h-2 w-2 rounded-full mr-1 ${billing.dot}`} />
            {billing.text}
          </span>
        )}
      </div>

      {error && <p className="text-sm text-accent mb-2">{error}</p>}

      {status && !status.can_open && (
        <p className="text-sm text-muted">{status.unavailable_reason ?? "The preview isn't available yet."}</p>
      )}

      {status?.can_open && (
        <>
          <div className="flex flex-wrap items-center gap-2 mb-3">
            {!iframeUrl ? (
              <button className="btn-primary text-sm" onClick={openPreview} disabled={opening}>
                {opening ? "Opening…" : pausedForIdle ? "Resume preview" : "Open preview"}
              </button>
            ) : (
              <>
                <button className="btn-default text-sm" onClick={openPreview} disabled={opening}>
                  {opening ? "Reloading…" : "Reload"}
                </button>
                <button className="btn-default text-sm" onClick={() => setIframeUrl(null)}>
                  Close
                </button>
              </>
            )}
            <button
              className="btn-default text-sm"
              onClick={restart}
              disabled={restarting}
              title="Restarts the app with your current preview secrets, without rebuilding."
            >
              {restarting ? "Restarting…" : "Restart app"}
            </button>
          </div>

          {pausedForIdle && !iframeUrl && (
            <p className="text-xs text-muted mb-2">
              Paused while this tab was in the background, so an open page can't keep the workspace running (and billing).
            </p>
          )}
          {restartNote && <p className="text-xs text-muted mb-2">{restartNote}</p>}

          {iframeUrl && (
            <iframe
              title="Live Preview"
              src={iframeUrl}
              className="w-full h-[60vh] min-h-[320px] border rounded bg-white"
              // The preview origin is a different site from this app, so allow-same-origin
              // only gives the framed app its OWN origin (it is what lets its cookies work);
              // it does not share anything with this page.
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals allow-downloads"
              referrerPolicy="no-referrer"
            />
          )}

          {status.origin && (
            <div className="mt-3 text-xs text-muted">
              <span>Preview address (permanent for this project): </span>
              <code className="mono text-ink">{status.origin}</code>{" "}
              <button className="underline" onClick={copyOrigin}>
                {copied ? "Copied" : "Copy"}
              </button>
              {status.entry_target && <span> · showing “{status.entry_target}”</span>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
