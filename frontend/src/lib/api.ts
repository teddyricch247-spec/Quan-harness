/**
 * Typed API Client for Quancis FastAPI Backend
 * Base URL configured via NEXT_PUBLIC_API_BASE_URL
 */

export class ApiError extends Error {
  status: number;
  type?: string;
  code?: string;

  constructor(status: number, message: string, type?: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.type = type;
    this.code = code;
  }
}

export interface PublicConfig {
  // GET /api/config's actual shape (main.py:public_config). Corrected
  // 2026-08-26 — the previous `models`/`pricing`/`default_model` fields
  // here didn't match anything the backend has ever returned; nothing
  // in the app reads `publicConfig` yet (see AppContext.tsx), so this
  // was never a runtime bug, just a wrong contract. Note this is also
  // where the Supabase URL/anon key are meant to come from — see
  // supabase.ts's own comment about the app currently using separate
  // NEXT_PUBLIC_SUPABASE_* build-time env vars instead of this endpoint.
  supabase_url?: string;
  supabase_anon_key?: string;
  products?: Array<{
    slug: string;
    label: string;
    tagline?: string;
    best_for?: string;
    context_window?: number;
    max_output?: number;
    // null for a product that exists but isn't priced/billed yet.
    customer_price_per_million?: {
      standard?: { input?: number; output?: number; cached_input?: number };
      [tier: string]: unknown;
    } | null;
    // The thinking levels this model accepts, and the one it uses when none is
    // sent (the same lists as MODELS below; the backend is the source).
    thinking_tiers?: string[];
    default_thinking_tier?: string;
    [key: string]: unknown;
  }>;
  [key: string]: unknown;
}

export interface MeResponse {
  id: string;
  email?: string;
  role?: string;
  is_admin?: boolean;
  created_at?: string;
  [key: string]: unknown;
}

export interface BillingLedgerEntry {
  id?: string;
  amount_usd: string;
  description?: string;
  type?: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface BillingResponse {
  balance_usd: string;
  // GET /api/billing (billing.py:fetch_billing_summary) does not
  // currently return this field at all — corrected 2026-08-26. Left
  // optional rather than removed: AppContext.tsx reads it defensively
  // already (`!= null` checks), so it degrades to `monthlySpend: null`
  // rather than breaking, and this stays a one-line no-op change if the
  // backend adds a real spend-total field later.
  total_spent_usd?: string;
  starting_balance_usd?: string;
  enabled?: boolean;
  ledger?: BillingLedgerEntry[];
  [key: string]: unknown;
}

export function getApiBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_BASE_URL || 'https://api.quancis.space';
  return url.replace(/\/+$/, '');
}

export async function apiRequest<T>(
  path: string,
  options?: {
    method?: string;
    body?: unknown;
    token?: string | null;
  }
): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  const url = `${baseUrl}${cleanPath}`;

  const headers: Record<string, string> = {};

  if (options?.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  if (options?.token) {
    headers['Authorization'] = `Bearer ${options.token}`;
  }

  const response = await fetch(url, {
    method: options?.method || 'GET',
    headers,
    body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const errorObj = (data as { error?: { message?: string; type?: string; code?: string } })?.error;
    const message = errorObj?.message || (typeof data === 'object' && data && 'detail' in data ? String((data as { detail: unknown }).detail) : '') || `Request failed with status ${response.status}`;
    const type = errorObj?.type;
    const code = errorObj?.code;

    throw new ApiError(response.status, message, type, code);
  }

  return data as T;
}

export async function fetchPublicConfig(): Promise<PublicConfig> {
  return apiRequest<PublicConfig>('/api/config');
}

export async function fetchMe(token: string): Promise<MeResponse> {
  return apiRequest<MeResponse>('/api/me', { token });
}

export async function fetchBilling(token: string): Promise<BillingResponse> {
  return apiRequest<BillingResponse>('/api/billing', { token });
}

export interface AuthMessageResponse {
  message: string;
}

export async function signUpEmail(email: string, password: string, name: string | undefined, termsAccepted: boolean): Promise<AuthMessageResponse> {
  return apiRequest<AuthMessageResponse>('/api/auth/signup', {
    method: 'POST',
    body: { email, password, name, terms_accepted: termsAccepted },
  });
}

export async function forgotPassword(email: string): Promise<AuthMessageResponse> {
  return apiRequest<AuthMessageResponse>('/api/auth/forgot-password', {
    method: 'POST',
    body: { email },
  });
}

// "I never got the confirmation email" — emails a fresh confirmation link
// to an unconfirmed account without touching its password. Same generic
// response whatever the account's state (see backend auth_email.resend_confirmation).
export async function resendConfirmation(email: string): Promise<AuthMessageResponse> {
  return apiRequest<AuthMessageResponse>('/api/auth/resend-confirmation', {
    method: 'POST',
    body: { email },
  });
}

// Called right after the signed-in user's password change succeeds in the
// browser (supabase.auth.updateUser), so the backend can email them a
// "your password was changed" notice. Best-effort; see backend
// account_emails.notify_password_changed.
export async function notifyPasswordChanged(token: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>('/api/auth/password-changed', {
    method: 'POST',
    token,
  });
}

export interface RecordOAuthConsentResponse {
  recorded: boolean;
  reason?: string;
}

// Called once, right after a Google/GitHub OAuth sign-in completes, IF
// (and only if) the pending-consent flag was set before the redirect —
// see AppContext's signInWithGitHub/signInWithGoogle and loadUserData
// for the full flow, and main.py's /api/auth/record-oauth-consent for
// why an authenticated call here is the actual trust boundary, not the
// client-side flag.
export async function recordOAuthConsent(token: string): Promise<RecordOAuthConsentResponse> {
  return apiRequest<RecordOAuthConsentResponse>('/api/auth/record-oauth-consent', {
    method: 'POST',
    token,
  });
}

export async function updateTheme(token: string, theme: 'light' | 'dark'): Promise<{ theme: string }> {
  return apiRequest<{ theme: string }>('/api/theme', {
    method: 'PATCH',
    token,
    body: { theme },
  });
}

export interface BackendApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
  // 'sdk' (the request decides) or a tier name. Absent on an older backend.
  thinking_level?: string;
}

export interface CreatedApiKey extends BackendApiKey {
  secret: string;
}

export interface ListApiKeysResponse {
  keys: BackendApiKey[];
}

export async function listApiKeys(token: string): Promise<ListApiKeysResponse> {
  return apiRequest<ListApiKeysResponse>('/api/keys', {
    token,
  });
}

export async function createApiKey(token: string, name: string, thinkingLevel: string = 'sdk'): Promise<CreatedApiKey> {
  return apiRequest<CreatedApiKey>('/api/keys', {
    method: 'POST',
    token,
    body: { name, thinking_level: thinkingLevel },
  });
}

export async function updateApiKeyThinkingLevel(
  token: string,
  id: string,
  thinkingLevel: string,
): Promise<{ id: string; thinking_level: string }> {
  return apiRequest<{ id: string; thinking_level: string }>(`/api/keys/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    token,
    body: { thinking_level: thinkingLevel },
  });
}

export async function deleteApiKey(token: string, id: string): Promise<{ revoked: boolean }> {
  return apiRequest<{ revoked: boolean }>(`/api/keys/${encodeURIComponent(id)}`, {
    method: 'DELETE',
    token,
  });
}

// Permanently deletes the signed-in user's account and everything stored against
// it (backend app/account.py). `confirm` is what the user typed: their account
// email address (or the word DELETE for an account with no email). The backend
// refuses admin accounts (403 admin_account) and a wrong confirmation (400
// confirmation_required); 502 delete_failed means nothing further was changed and
// the caller can try again.
export async function deleteAccount(token: string, confirm: string): Promise<{ deleted: boolean }> {
  return apiRequest<{ deleted: boolean }>('/api/account', {
    method: 'DELETE',
    token,
    body: { confirm },
  });
}

export interface ChatSession {
  // Matches supabase_client.py's list_chat_sessions/get_chat_session
  // `select` exactly — corrected 2026-08-26. Two real differences from
  // before: the backend's field is `model`, not `product` (every place
  // that read `.product` was silently reading `undefined` — see
  // AppContext.tsx and PlaygroundPage.tsx, now fixed to read `.model`);
  // and `user_id` is never actually selected by either query (ownership
  // is enforced server-side, not exposed to the client), so it's
  // dropped here rather than left promising a field that never arrives.
  id: string;
  title: string;
  // The model the conversation is locked to: 'kael-beta' or 'kael-pro-beta'
  // (its public slug). Any other value is a legacy conversation, which the
  // backend reports as `resumable: false` and which can be read but not
  // continued. Typed as a loose `string` on purpose, so a value this app does
  // not know shows as legacy instead of being trusted. Use modelInfo() to check.
  model: string;
  thinking_enabled: boolean;
  reasoning_effort: string | null;
  created_at: string;
  last_message_at: string;
  // false for a legacy session (an option this app no longer offers) that can
  // be read but not continued. Sent by the backend on both the list and the
  // detail routes since 2026-10-04; undefined from an older backend, which
  // callers treat as resumable.
  resumable?: boolean;
}

// Same cap the backend enforces (chat_history.MAX_MESSAGE_CHARS).
export const CHAT_MESSAGE_MAX_CHARS = 100_000;

// A picture attached to a saved message. The list carries no bytes: they are
// fetched one at a time with fetchChatImage().
export interface ChatSessionImage {
  id: string;
  mime: string;
}

export interface ChatSessionMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
  // Pictures the user attached (user messages only; absent when there are none).
  images?: ChatSessionImage[];
  // The thinking titles Kael streamed for this reply, in order (assistant
  // messages only). Empty/absent for replies saved before the backend started
  // keeping them.
  thinking?: string[];
}

// A reply that is still being generated (or failed before it could be saved),
// reported by GET /api/chat/sessions/{id}. This is what lets a page that went
// offline or was reloaded mid-reply pick the reply back up.
export interface ChatPendingReply {
  status: 'running' | 'error';
  // The user's message this reply answers (not in `messages` yet).
  content: string;
  // How many pictures that message carried (0 or absent: none).
  image_count?: number;
  started_at: string;
  thinking: string[];
  // Answer text so far.
  answer: string;
  reasoning_effort?: ThinkingLevel | null;
  error?: { message: string; type?: string | null; code?: string | null; status?: number | null } | null;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatSessionMessage[];
  pending?: ChatPendingReply | null;
}

// Every thinking level (the API's reasoning_effort) that any model accepts.
// Each model accepts only its own levels (see MODELS below): sending a level to
// the other model is a 400. There is no "off": Kael always thinks, and leaving
// the field out means the model's own default level.
export type ThinkingLevel = 'low' | 'high' | 'max' | 'z-low' | 'z-high';
export const THINKING_LEVELS: ThinkingLevel[] = ['low', 'high', 'max', 'z-low', 'z-high'];

// The two public models. One entry each, in the order the picker shows them.
// Mirrors backend/app/models/kael/config.py (reasoning_tiers and
// default_reasoning_tier; GET /api/config returns the same lists as
// `thinking_tiers` and `default_thinking_tier`). If they disagree, the backend
// wins: fix this file. Prices are not here; they live in components/docs/facts.ts.
export type ModelId = 'kael-beta' | 'kael-pro-beta';

export interface ModelInfo {
  id: ModelId;
  // Display name.
  name: string;
  // One line for the picker.
  summary: string;
  levels: ThinkingLevel[];
  defaultLevel: ThinkingLevel;
}

export const MODELS: ModelInfo[] = [
  {
    id: 'kael-beta',
    name: 'Kael Beta',
    summary: 'Fast, sharp reasoning for everyday problems.',
    levels: ['low', 'high', 'max'],
    defaultLevel: 'low',
  },
  {
    id: 'kael-pro-beta',
    name: 'Kael Pro Beta',
    summary: 'Our most thorough reasoning, for the hardest problems. Costs more per token.',
    levels: ['z-low', 'z-high'],
    defaultLevel: 'z-low',
  },
];

export const DEFAULT_MODEL: ModelId = 'kael-beta';

// The catalog entry for a model slug, or undefined for anything that is not a
// current model (a legacy conversation, an unknown value).
export const modelInfo = (model: string | null | undefined): ModelInfo | undefined =>
  MODELS.find((m) => m.id === model);

export const isModelId = (model: unknown): model is ModelId => MODELS.some((m) => m.id === model);

// A thinking level this model accepts, or its default. Used to turn a stored or
// stale value into one the model will not reject.
export const levelForModel = (model: ModelId, level: string | null | undefined): ThinkingLevel => {
  const info = modelInfo(model) ?? MODELS[0];
  return info.levels.find((l) => l === level) ?? info.defaultLevel;
};

export interface ListChatSessionsResponse {
  sessions: ChatSession[];
}

export async function createChatSession(
  token: string,
  model: ModelId = DEFAULT_MODEL
): Promise<ChatSession> {
  // The backend still names this body field `product`.
  return apiRequest<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    token,
    body: { product: model },
  });
}

export async function listChatSessions(token: string): Promise<ListChatSessionsResponse> {
  return apiRequest<ListChatSessionsResponse>('/api/chat/sessions', {
    token,
  });
}

export async function getChatSession(token: string, sessionId: string): Promise<ChatSessionDetail> {
  return apiRequest<ChatSessionDetail>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
    token,
  });
}

export async function renameChatSession(
  token: string,
  sessionId: string,
  title: string
): Promise<{ renamed: boolean; title?: string }> {
  return apiRequest<{ renamed: boolean; title?: string }>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    token,
    body: { title },
  });
}

export async function deleteChatSession(
  token: string,
  sessionId: string
): Promise<{ deleted: boolean }> {
  return apiRequest<{ deleted: boolean }>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    token,
  });
}

// The bytes of one saved picture, fetched with the login token (a picture is
// never reachable by URL alone).
export async function fetchChatImage(token: string, sessionId: string, imageId: string): Promise<Blob> {
  const response = await fetch(
    `${getApiBaseUrl()}/api/chat/sessions/${encodeURIComponent(sessionId)}/images/${encodeURIComponent(imageId)}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!response.ok) throw new ApiError(response.status, `Could not load the picture (${response.status}).`);
  return response.blob();
}

// Voice typing: sends one recording (raw bytes, any browser audio type) and gets
// back what was said, as text in the spoken language. The audio is not kept and
// never goes to Kael; see backend/app/transcription.py.
export async function transcribeAudio(token: string, audio: Blob): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}/api/chat/transcribe`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': audio.type || 'application/octet-stream' },
      body: audio,
    });
  } catch {
    throw new ApiError(0, "Couldn't reach Quancis. Check your connection and try again.");
  }
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const err = (data as { error?: { message?: string; type?: string; code?: string } } | null)?.error;
    throw new ApiError(
      response.status,
      err?.message || `Voice typing failed (${response.status}). You can still type your message.`,
      err?.type,
      err?.code
    );
  }
  const text = (data as { text?: unknown } | null)?.text;
  return typeof text === 'string' ? text : '';
}

// A picture sent with a message: base64 of the bytes (no "data:" prefix) and its type.
export interface ChatImageUpload {
  data: string;
  mime: string;
}

export interface StreamChatCallbacks {
  onToken: (delta: string) => void;
  onDone: (fullText: string) => void;
  onError: (err: Error) => void;
  onFirstToken?: () => void;
  // The backend's "thinking titles" (delta.reasoning_content): short,
  // already-condensed sentences describing what Kael is working on. Each call
  // is one complete title, not a fragment to concatenate.
  onThinking?: (title: string) => void;
}

// Code on the ApiError thrown when the connection dropped (offline, tab
// suspended, proxy cut the stream) rather than the server answering with an
// error. The reply may well still be running on the server, so callers should
// look for it (GET /api/chat/sessions/{id}, `pending`) instead of reporting a
// failure.
export const CONNECTION_LOST = 'connection_lost';

export async function streamChatSessionMessage(
  token: string,
  sessionId: string,
  content: string,
  callbacks: StreamChatCallbacks,
  options?: { reasoningEffort?: ThinkingLevel; images?: ChatImageUpload[] }
): Promise<void> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        content,
        stream: true,
        ...(options?.images && options.images.length > 0 ? { images: options.images } : {}),
        ...(options?.reasoningEffort ? { reasoning_effort: options.reasoningEffort } : {}),
      }),
    });
  } catch (netErr: any) {
    const err = new ApiError(0, netErr?.message || "Couldn't reach Quancis, please try again.", undefined, CONNECTION_LOST);
    callbacks.onError(err);
    throw err;
  }

  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    const errorObj = (data as { error?: { message?: string; type?: string; code?: string } })?.error;
    const message =
      errorObj?.message ||
      (typeof data === 'object' && data && 'detail' in data ? String((data as { detail: unknown }).detail) : '') ||
      `Request failed with status ${response.status}`;
    const type = errorObj?.type;
    const code = errorObj?.code;

    const apiErr = new ApiError(response.status, message, type, code);
    callbacks.onError(apiErr);
    throw apiErr;
  }

  if (!response.body) {
    const err = new ApiError(response.status, 'No response body stream received from server');
    callbacks.onError(err);
    throw err;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let fullText = '';
  let receivedFirstToken = false;
  let sawDone = false;

  // One SSE `data:` payload. Throws an ApiError for an in-stream error frame
  // (`data: {"error": {...}}`, which the backend sends when a pass fails after
  // the response has already started with a 200); the old client ignored
  // those and the user saw an empty reply bubble with no explanation.
  const consume = (dataStr: string) => {
    if (dataStr === '[DONE]') {
      sawDone = true;
      return;
    }
    let parsed: any;
    try {
      parsed = JSON.parse(dataStr);
    } catch {
      return; // partial or unparseable line
    }
    if (parsed?.error) {
      throw new ApiError(
        502,
        parsed.error.message || 'The reply was interrupted. Please try again.',
        parsed.error.type,
        parsed.error.code
      );
    }
    const delta = parsed?.choices?.[0]?.delta;
    const thinking = delta?.reasoning_content;
    if (typeof thinking === 'string' && thinking.trim().length > 0) {
      callbacks.onThinking?.(thinking.trim());
    }
    const text = delta?.content;
    if (typeof text === 'string' && text.length > 0) {
      if (!receivedFirstToken) {
        receivedFirstToken = true;
        callbacks.onFirstToken?.();
      }
      fullText += text;
      callbacks.onToken(text);
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      // Keep unfinished piece in buffer
      buffer = lines.pop() ?? '';

      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line || !line.startsWith('data:')) continue;
        consume(line.slice(5).trim());
      }
    }

    const tail = buffer.trim();
    if (tail.startsWith('data:')) consume(tail.slice(5).trim());

    // The backend always ends a stream with [DONE]. A stream that just stops
    // was cut off (a proxy, a restart, a suspended tab): the reply may still
    // be finishing on the server, so say "connection lost", not "empty".
    if (!sawDone) {
      throw new ApiError(0, 'The connection was interrupted before the reply finished.', undefined, CONNECTION_LOST);
    }

    // A stream that ends without any answer text is a failure, not an empty
    // success (the page used to render a blank assistant bubble).
    if (fullText.trim().length === 0) {
      throw new ApiError(502, 'Kael returned an empty reply. Please try again.', 'server_error', 'empty_reply');
    }

    callbacks.onDone(fullText);
  } catch (streamErr: any) {
    // A dropped connection mid-stream surfaces as a bare TypeError from fetch.
    const err =
      streamErr instanceof ApiError
        ? streamErr
        : new ApiError(0, 'The connection was interrupted before the reply finished.', undefined, CONNECTION_LOST);
    callbacks.onError(err);
    throw err;
  }
}

export interface ChatCompletionChoice {
  index: number;
  message: {
    role: 'assistant' | 'user' | 'system';
    content: string;
  };
  finish_reason?: string;
}

export interface ChatCompletionResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: ChatCompletionChoice[];
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export async function sendChatCompletion(
  apiKeySecret: string,
  messages: Array<{ role: string; content: string }>,
  model: ModelId = DEFAULT_MODEL
): Promise<ChatCompletionResponse> {
  return apiRequest<ChatCompletionResponse>(`/${model}/v1/chat/completions`, {
    method: 'POST',
    token: apiKeySecret,
    body: {
      model,
      messages,
    },
  });
}

// GET /api/stats (supabase_client.fetch_stats). Scoped to the signed-in
// account only. `daily` and `recent` are already shaped server-side to
// match UsageDay/RequestLog field-for-field (see AppContext.tsx's
// loadStats) — this is real usage_logs data.
export interface StatsDailyEntry {
  date: string;
  input_tokens: number;
  cached_tokens: number;
  output_tokens: number;
  total_requests: number;
  cost_usd: number;
  avg_latency_ms: number;
}

export interface StatsRecentEntry {
  id: string;
  timestamp: string;
  endpoint: string;
  model: string;
  status: number;
  tokens: number;
  cache_hit: boolean;
  latency_ms: number;
  cost_usd: number;
}

export interface StatsByProductEntry {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  total_tokens: number;
}

export interface StatsResponse {
  enabled: boolean;
  window_days?: number;
  totals?: {
    requests: number;
    prompt_tokens: number;
    completion_tokens: number;
    cached_tokens: number;
    total_tokens: number;
    errors: number;
  };
  estimated_cost_usd?: number;
  by_product?: Record<string, StatsByProductEntry>;
  daily?: StatsDailyEntry[];
  recent?: StatsRecentEntry[];
}

export async function fetchStats(token: string, days: number = 30): Promise<StatsResponse> {
  return apiRequest<StatsResponse>(`/api/stats?days=${days}`, { token });
}

export interface AdminStats {
  total_users: number;
  revenue_in_window_usd: string;
  requests_in_window: number;
  cache_hit_rate_in_window: number | null;
  active_api_keys: number;
  window_days: number;
}

export interface AdminUserRecord {
  id: string;
  email: string;
  github_username: string | null;
  created_at: string;
  status: 'active' | 'suspended';
  is_admin: boolean;
  credit_balance_usd: string | null;
  total_spend_usd: string;
  total_requests: number;
  // Both returned by GET /api/admin/users (admin.py:get_users) but not
  // previously declared here or rendered in AdminPage.tsx — added
  // 2026-08-26 for accuracy; wiring them into the table is a separate,
  // optional follow-up, not done as part of this fix.
  last_active: string | null;
  active_keys_count: number;
}

export interface CreditAdminUserResponse {
  user_id: string;
  credited_usd: string;
  new_balance_usd: string;
  // True when an admin credited their own account. Decided by the backend
  // (user_id == the caller), not by a request flag: it is not a purchase, so it
  // is labelled "Admin self-credit" in the ledger.
  self_credit?: boolean;
}

export interface SuspendAdminUserResponse {
  user_id: string;
  status: 'suspended';
  api_keys_revoked: number;
}

export interface ActivateAdminUserResponse {
  user_id: string;
  status: 'active';
}

// POST /api/admin/reconcile (app/admin.py run_reconcile_check). Read-only: it
// compares every account's balance to its ledger history and changes nothing.
// A check that could not run comes back as an HTTP 502 (thrown as ApiError by
// apiRequest), never as a 200, so "could not verify" can't look like "clean".
export interface ReconcileDrift {
  user_id: string;
  expected_balance_usd: string;
  actual_balance_usd: string;
  drift_usd: string; // signed: negative = the account has LESS than its ledger accounts for
}

export interface ReconcileAdminResponse {
  status: 'ok' | 'drift';
  checked_at: string; // ISO 8601, UTC
  drift_count: number;
  drifts: ReconcileDrift[];
  error: string | null;
}

export async function getAdminStats(token: string): Promise<AdminStats> {
  return apiRequest<AdminStats>('/api/admin/stats', {
    method: 'GET',
    token,
  });
}

export async function getAdminUsers(token: string): Promise<{ users: AdminUserRecord[] }> {
  return apiRequest<{ users: AdminUserRecord[] }>('/api/admin/users', {
    method: 'GET',
    token,
  });
}

export async function creditAdminUser(
  token: string,
  userId: string,
  amountUsd: number
): Promise<CreditAdminUserResponse> {
  return apiRequest<CreditAdminUserResponse>(`/api/admin/users/${userId}/credit`, {
    method: 'POST',
    token,
    body: {
      amount_usd: amountUsd,
    },
  });
}

export async function suspendAdminUser(
  token: string,
  userId: string
): Promise<SuspendAdminUserResponse> {
  return apiRequest<SuspendAdminUserResponse>(`/api/admin/users/${userId}/suspend`, {
    method: 'POST',
    token,
  });
}

export async function activateAdminUser(
  token: string,
  userId: string
): Promise<ActivateAdminUserResponse> {
  return apiRequest<ActivateAdminUserResponse>(`/api/admin/users/${userId}/activate`, {
    method: 'POST',
    token,
  });
}

export async function runAdminReconcile(token: string): Promise<ReconcileAdminResponse> {
  return apiRequest<ReconcileAdminResponse>('/api/admin/reconcile', {
    method: 'POST',
    token,
  });
}

