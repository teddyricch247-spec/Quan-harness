"use client";

/**
 * Phase Convert (C4/C5 Flow B–C): what Code home knows when it navigates to a project it just
 * created, and the workspace needs once: the first session, whether its first turn started, the
 * prompt (so a failed start can be retried), and an import's pull error. Kept in sessionStorage so
 * it survives the navigation and nothing else — it is read once and removed. GET /projects/{id}
 * never carries these (they are properties of the create call, not of the project).
 */
export interface StartHandoff {
  session_id?: string;
  turn_status?: "running" | "not_started" | "failed";
  prompt?: string;
  import_pull_error?: string | null;
}

const key = (projectId: string) => `qh:start:${projectId}`;

export function saveHandoff(projectId: string, handoff: StartHandoff): void {
  try {
    window.sessionStorage.setItem(key(projectId), JSON.stringify(handoff));
  } catch {
    // no storage → the workspace simply opens without the one-time extras
  }
}

export function takeHandoff(projectId: string): StartHandoff | null {
  try {
    const raw = window.sessionStorage.getItem(key(projectId));
    if (!raw) return null;
    window.sessionStorage.removeItem(key(projectId));
    return JSON.parse(raw) as StartHandoff;
  } catch {
    return null;
  }
}
