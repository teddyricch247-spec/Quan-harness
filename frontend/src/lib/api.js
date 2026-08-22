import { supabase } from '../supabaseClient.js';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

async function authHeader() {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  if (!token) throw new Error('Not signed in.');
  return `Bearer ${token}`;
}

export async function apiFetch(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    Authorization: await authHeader(),
    ...options.headers,
  };
  const res = await fetch(`${BACKEND_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  listProjects: () => apiFetch('/api/projects'),
  createProject: (name, githubRepo) => apiFetch('/api/projects', { method: 'POST', body: JSON.stringify({ name, github_repo: githubRepo }) }),
  getProject: (id) => apiFetch(`/api/projects/${id}`),
  listSessions: (projectId) => apiFetch(`/api/projects/${projectId}/sessions`),
  createSession: (projectId, title, kind) =>
    apiFetch(`/api/projects/${projectId}/sessions`, { method: 'POST', body: JSON.stringify({ title, kind }) }),
  updateSession: (sessionId, patch) => apiFetch(`/api/sessions/${sessionId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  getSession: (sessionId) => apiFetch(`/api/sessions/${sessionId}`),
  listMessages: (sessionId) => apiFetch(`/api/sessions/${sessionId}/messages`),
  // { providers: [{ id, label, reasoningEfforts }] } — just 'deepseek' unless a
  // custom provider is configured on the backend.
  getMeta: () => apiFetch('/api/meta'),
  backendUrl: BACKEND_URL,
  authHeader,
};
