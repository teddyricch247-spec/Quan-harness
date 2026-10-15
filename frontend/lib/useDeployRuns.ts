"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "./api";
import type { DeployRun } from "./types";

// Phase 5.1/5.2/5.5 (§23.5/§23.6/§23.9). Polling rather than the backend's own /deploy/stream SSE
// endpoint. (lib/stream.ts now solves the "EventSource can't send an Authorization header" problem
// for the agent stream; moving deploys onto it is a possible follow-up, not part of Convert.)
const POLL_MS = 2000;
const DIAGNOSIS_WAIT_MS = 90_000;

/**
 * Phase Convert (C7): the deploy runs, lifted out of DeployPanel so the Preview tab's status line
 * and the Deploy sheet read the same list from one place. Polls while a run is in flight, and for a
 * little while after a failure so the diagnosis (written a few seconds later, §23.9 point 2) shows
 * up on its own — but stops after DIAGNOSIS_WAIT_MS, since a diagnosis can legitimately never
 * arrive (no LLM credential, provider down).
 */
export function useDeployRuns(projectId: string): { runs: DeployRun[]; loaded: boolean; refresh: () => void; startPolling: () => void } {
  const [runs, setRuns] = useState<DeployRun[]>([]);
  const [loaded, setLoaded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    apiFetch<DeployRun[]>(`/projects/${projectId}/deploy/runs`)
      .then((r) => {
        setRuns(r);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [projectId]);

  useEffect(() => {
    refresh();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [refresh]);

  const latest = runs[0] ?? null;

  useEffect(() => {
    const diagnosisPending =
      !!latest &&
      latest.status === "failed" &&
      !latest.diagnosis_text &&
      !!latest.completed_at &&
      Date.now() - new Date(latest.completed_at).getTime() < DIAGNOSIS_WAIT_MS;
    const active = runs.some((r) => r.status === "running") || diagnosisPending;
    if (active && !pollRef.current) {
      pollRef.current = setInterval(refresh, POLL_MS);
    } else if (!active && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [runs, latest, refresh]);

  // A deploy was just triggered: the list doesn't show a running run yet, so poll right away.
  const startPolling = useCallback(() => {
    refresh();
    if (!pollRef.current) pollRef.current = setInterval(refresh, POLL_MS);
  }, [refresh]);

  return { runs, loaded, refresh, startPolling };
}
