"use client";

import { supabase } from "./supabaseClient";
import { parseErrorDetail } from "./errors";
import type { AttentionOut, GithubCredential, Project, ProjectStartOut } from "./types";

export { parseErrorDetail };

const API_URL = process.env.NEXT_PUBLIC_API_URL as string;

export class ApiError extends Error {
  status: number;
  // Phase Convert (C8.1): a stable machine-readable code when the backend sent `{code, message}`
  // (only POST /projects does, for email_not_verified / llm_key_required / github_not_connected).
  // Undefined for every other error, whose `detail` is still a plain string. The UI branches on
  // `code`, never on message text.
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function apiUrl(path: string): string {
  return `${API_URL}${path}`;
}

/**
 * §4: "the frontend receives a JWT and attaches it as a Bearer token to every
 * backend request." This is the one place that happens — every page in app/
 * calls through here rather than using fetch() directly, so that rule can't be
 * accidentally skipped on some new page later.
 */
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const auth = await authHeaders();
  if (auth.Authorization) headers.set("Authorization", auth.Authorization);

  const res = await fetch(apiUrl(path), { ...options, headers });

  if (!res.ok) {
    let parsed: { message: string; code?: string } = { message: res.statusText };
    try {
      parsed = parseErrorDetail(await res.json(), res.statusText);
    } catch {
      // body wasn't JSON — fall back to statusText
    }
    throw new ApiError(res.status, parsed.message, parsed.code);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Phase Convert (C7): the three calls the new shell and Code home add.
// ---------------------------------------------------------------------------

export interface StartProjectInput {
  prompt?: string;
  mode?: "scratch" | "import" | "create_new_repo";
  github_repo?: string; // "owner/repo", mode === "import"
  new_repo_name?: string; // mode === "create_new_repo"
  new_repo_private?: boolean;
  llm_credential_id?: string; // only when the person picked a non-default model
  connector_ids?: string[];
}

/**
 * POST /projects. With a non-empty `prompt` the backend creates the project, its first session and
 * the first turn in one call and answers ProjectStartOut; with no prompt (an import with nothing
 * typed) it answers a plain Project. Callers branch on `"project" in result`.
 */
export function startProject(input: StartProjectInput): Promise<ProjectStartOut | Project> {
  return apiFetch<ProjectStartOut | Project>("/projects", { method: "POST", body: JSON.stringify(input) });
}

export function getAttention(): Promise<AttentionOut> {
  return apiFetch<AttentionOut>("/attention");
}

export function setGithubDefault(credentialId: string): Promise<GithubCredential> {
  return apiFetch<GithubCredential>(`/connections/github-credential/${credentialId}/set-default`, { method: "POST" });
}

export function isStartOut(result: ProjectStartOut | Project): result is ProjectStartOut {
  return "project" in result && "session_id" in result;
}
