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
  // { providers: [{ id, label, reasoningEfforts }] } — whatever's configured in
  // Settings; empty until at least one provider is added there.
  getMeta: () => apiFetch('/api/meta'),

  // Settings — BYOK model providers and other API keys (GitHub, Vercel, Tavily, ...).
  // apiKey/value are only ever sent up, never back down — the backend returns a
  // masked preview (apiKeyPreview) / a hasValue flag instead of the real thing.
  listProviderSettings: () => apiFetch('/api/settings/providers'),
  saveProviderSetting: (id, patch) =>
    apiFetch(`/api/settings/providers/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(patch) }),
  deleteProviderSetting: (id) => apiFetch(`/api/settings/providers/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listSecrets: () => apiFetch('/api/settings/secrets'),
  saveSecret: (key, value, label) =>
    apiFetch(`/api/settings/secrets/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify({ value, label }) }),
  deleteSecret: (key) => apiFetch(`/api/settings/secrets/${encodeURIComponent(key)}`, { method: 'DELETE' }),

  backendUrl: BACKEND_URL,
  authHeader,
};
