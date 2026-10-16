'use client';

import React, { createContext, useContext, useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { ApiKey, ChatMessage, ChatMessageImage, RequestLog, UsageDay, UserProfile } from '../types';
import { getSupabase, isSupabaseConfigured } from '../lib/supabase';
import { isThinkingFiller } from '../lib/thinkingFillers';
import { playgroundSessionPath } from '../lib/routes';
import {
  ActivateAdminUserResponse,
  AdminStats,
  AdminUserRecord,
  ApiError,
  BillingResponse,
  CONNECTION_LOST,
  ChatSession,
  ChatSessionDetail,
  DEFAULT_MODEL,
  MODELS,
  ModelId,
  ThinkingLevel,
  CreatedApiKey,
  CreditAdminUserResponse,
  PublicConfig,
  ReconcileAdminResponse,
  StatsByProductEntry,
  SuspendAdminUserResponse,
  activateAdminUser as activateAdminUserApi,
  createApiKey as createApiKeyApi,
  createChatSession,
  creditAdminUser as creditAdminUserApi,
  deleteApiKey as deleteApiKeyApi,
  deleteAccount as deleteAccountApi,
  deleteChatSession as deleteChatSessionApi,
  fetchBilling,
  fetchMe,
  fetchPublicConfig,
  fetchStats,
  forgotPassword as forgotPasswordApi,
  getAdminStats as getAdminStatsApi,
  getAdminUsers as getAdminUsersApi,
  getChatSession,
  isModelId,
  levelForModel,
  listApiKeys as listApiKeysApi,
  listChatSessions,
  recordOAuthConsent as recordOAuthConsentApi,
  renameChatSession as renameChatSessionApi,
  resendConfirmation as resendConfirmationApi,
  notifyPasswordChanged as notifyPasswordChangedApi,
  runAdminReconcile as runAdminReconcileApi,
  signUpEmail as signUpEmailApi,
  streamChatSessionMessage,
  suspendAdminUser as suspendAdminUserApi,
  updateApiKeyThinkingLevel as updateApiKeyThinkingLevelApi,
} from '../lib/api';

// Set in localStorage (not sessionStorage — needs to survive the
// full-page redirect to Google/GitHub and back) immediately before an
// OAuth sign-in is started, but ONLY if the Terms/Privacy checkbox was
// checked at that moment. loadUserData below looks for this exactly
// once, right after a session is established, and — if present — makes
// an authenticated call to record consent server-side, then clears it.
// See main.py's /api/auth/record-oauth-consent for why the actual
// security boundary is that authenticated call, not this flag.
const PENDING_OAUTH_CONSENT_KEY = 'quancis_pending_oauth_consent';

// Default shown in the Notifications tab before the user has ever saved
// a threshold of their own — matches the number the old mocked-up
// AccountPage used to hardcode, kept only as a sane starting point.
const DEFAULT_LOW_BALANCE_THRESHOLD_USD = 10;

// Single source of truth for turning a Supabase Auth session user (plus,
// where available, this backend's own /api/me + /api/billing data) into
// the UserProfile shape the rest of the app reads. Used by all three
// places a session gets turned into a profile below (initial load,
// onAuthStateChange, and loadUserData) so a field added here — like
// `provider` and the notification prefs — can't accidentally be missed
// in one of the three and cause it to silently fall back to a stale
// default depending on which code path happened to run.
//
// Email is read from `overrides.email` (backend's /api/me, when
// available) or sessionUser.email directly — both come straight from
// Supabase/GoTrue regardless of which provider signed the user in, so
// this is always the real address, never a placeholder. If Supabase
// genuinely has no email on file for this account (rare — e.g. a GitHub
// account with a fully private email and no email scope granted), this
// returns '' rather than a fake-looking fallback address; callers
// display that as "No email on file" instead of showing something that
// looks real but isn't.
function buildProfileFromSession(
  sessionUser: any,
  overrides: {
    id?: string;
    email?: string;
    role?: 'admin' | 'user';
    creditBalance?: number | null;
    monthlySpend?: number | null;
  } = {}
): UserProfile {
  const meta = sessionUser.user_metadata || {};
  const appMeta = sessionUser.app_metadata || {};

  return {
    id: overrides.id || sessionUser.id,
    name: meta.full_name || meta.user_name || meta.name || sessionUser.email?.split('@')[0] || 'Developer',
    email: overrides.email || sessionUser.email || '',
    avatar: meta.avatar_url || 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
    tier: 'Scale',
    role: overrides.role || 'user',
    creditBalance: overrides.creditBalance ?? null,
    monthlySpend: overrides.monthlySpend ?? null,
    createdAt: sessionUser.created_at?.split('T')[0] || '2026-03-01',
    // GoTrue sets this to the primary sign-in provider ('email',
    // 'google', 'github') and it lives in app_metadata, which is
    // service-role-only to write — the user themselves can't spoof it
    // by editing their own user_metadata.
    provider: appMeta.provider || 'email',
    lowBalanceAlertEnabled: Boolean(meta.low_balance_alert_enabled),
    lowBalanceAlertThresholdUsd:
      typeof meta.low_balance_alert_threshold_usd === 'number'
        ? meta.low_balance_alert_threshold_usd
        : DEFAULT_LOW_BALANCE_THRESHOLD_USD,
  };
}

// The assistant greeting shown in an empty playground conversation. It is not a stored message,
// so it carries no timestamp (it used to be hard-coded to "10:00 AM").
const makeWelcomeMessage = (): ChatMessage => ({
  id: 'msg_welcome',
  role: 'assistant',
  content: "Hi, I'm Kael. What would you like to work on?",
  timestamp: '',
  model: 'kael-beta',
});

// Label stored on each loaded message; PlaygroundPage maps it to a display
// name. It is the conversation's model (kael-beta or kael-pro-beta). A
// conversation the backend says is not resumable, or whose model is not one this
// app offers, is a legacy one (made with a model that no longer exists).
const modelLabelForSession = (model: string, resumable: boolean): string =>
  resumable && isModelId(model) ? model : 'legacy';

const clockTime = (): string => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// The playground's model and thinking levels are per-browser preferences (the
// backend takes the level per message), remembered between visits. Each model
// has its own level, because each model accepts different ones: Kael Beta takes
// low / high / max, Kael Pro Beta takes z-low / z-high.
const THINKING_LEVELS_STORAGE_KEY = 'quan_playground_thinking_levels';
const SELECTED_MODEL_STORAGE_KEY = 'quan_playground_model';
// Read once for people who set a level before there were two models (it was Kael
// Beta's level then). Never written again.
const LEGACY_THINKING_LEVEL_STORAGE_KEY = 'quan_playground_thinking_level';

type ThinkingLevels = Record<ModelId, ThinkingLevel>;

const defaultThinkingLevels = (): ThinkingLevels =>
  Object.fromEntries(MODELS.map((m) => [m.id, m.defaultLevel])) as ThinkingLevels;

const readStoredThinkingLevels = (): ThinkingLevels => {
  const levels = defaultThinkingLevels();
  try {
    const raw = localStorage.getItem(THINKING_LEVELS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      for (const m of MODELS) levels[m.id] = levelForModel(m.id, typeof parsed[m.id] === 'string' ? (parsed[m.id] as string) : null);
    } else {
      levels[DEFAULT_MODEL] = levelForModel(DEFAULT_MODEL, localStorage.getItem(LEGACY_THINKING_LEVEL_STORAGE_KEY));
    }
  } catch {
    // Storage blocked (private mode) or unreadable: fall through to the defaults.
  }
  return levels;
};

const readStoredModel = (): ModelId => {
  try {
    const raw = localStorage.getItem(SELECTED_MODEL_STORAGE_KEY);
    if (isModelId(raw)) return raw;
  } catch {
    // Storage blocked: the default model.
  }
  return DEFAULT_MODEL;
};

// How often a reply that is still running on the server is checked while the
// page is following it after a reload or a lost connection, and how long that
// is kept up (the backend's own request limit is 15 minutes).
const FOLLOW_POLL_MS = 2000;
const FOLLOW_MAX_MS = 17 * 60 * 1000;

// Waits `ms`, but wakes up early when the browser comes back online or the tab
// becomes visible again, so a reload-after-offline catches up immediately
// instead of at the next tick.
const waitOrWake = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      window.removeEventListener('online', done);
      document.removeEventListener('visibilitychange', onVisible);
      resolve();
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') done();
    };
    const timer = setTimeout(done, ms);
    window.addEventListener('online', done);
    document.addEventListener('visibilitychange', onVisible);
  });

// Turns a stored chat into the page's messages. Ids are stable across reloads
// of the same chat. `pending` (a reply still running, or one that failed
// before it could be saved) becomes the last user + assistant pair.
const mapSessionDetail = (detail: ChatSessionDetail, modelLabel: string): ChatMessage[] => {
  const mapped: ChatMessage[] = (detail.messages || []).map((m, idx) => ({
    id: `sess_msg_${detail.id}_${idx}`,
    role: m.role,
    content: m.content,
    timestamp: m.created_at ? new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '',
    model: modelLabel,
    ...(m.role === 'assistant' && m.thinking && m.thinking.length > 0 ? { thinking: m.thinking } : {}),
    // Saved pictures: only their ids; the page fetches the bytes when it shows them.
    ...(m.role === 'user' && m.images && m.images.length > 0 ? { images: m.images.map((i) => ({ id: i.id, mime: i.mime })) } : {}),
  }));
  const p = detail.pending;
  if (p) {
    const startedAt = new Date(p.started_at);
    const stamp = Number.isNaN(startedAt.getTime()) ? '' : startedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    mapped.push({
      id: `sess_pending_user_${detail.id}`,
      role: 'user',
      content: p.content,
      timestamp: stamp,
      model: modelLabel,
      // The message's pictures are saved together with the reply, so while the reply
      // is still running only their number is known.
      ...(p.image_count ? { imageCount: p.image_count } : {}),
    });
    const thinking = p.thinking || [];
    mapped.push({
      id: `sess_pending_asst_${detail.id}`,
      role: 'assistant',
      content: p.answer || '',
      timestamp: stamp,
      model: modelLabel,
      thinking,
      thinkingLabel: p.status === 'running' && !p.answer ? thinking[thinking.length - 1] : undefined,
      ...(p.status === 'error'
        ? {
            error:
              (p.error?.message || 'The reply was interrupted. Please try again.') +
              // The pictures were not kept with a failed reply, so a plain Retry
              // would resend the text alone.
              (p.image_count ? ' Attach your pictures again to resend.' : ''),
          }
        : {}),
    });
  }
  return mapped;
};

export interface AppContextType {
  isLoggedIn: boolean;
  // False until the initial supabase.auth.getSession() check resolves.
  // Route guards must wait for this before deciding to redirect —
  // isLoggedIn alone can't tell "confirmed logged out" apart from
  // "haven't checked yet" (it starts false either way).
  authChecked: boolean;
  user: UserProfile | null;
  publicConfig: PublicConfig | null;
  billing: BillingResponse | null;
  billingLoading: boolean;
  refreshBilling: () => Promise<void>;
  login: (email?: string, name?: string) => void;
  logout: () => Promise<void>;
  deleteAccount: (confirm: string) => Promise<{ error: string | null }>;
  signInWithGitHub: (consentGiven: boolean) => Promise<{ error: string | null }>;
  signInWithGoogle: (consentGiven: boolean) => Promise<{ error: string | null }>;
  signInWithEmail: (email: string, password: string) => Promise<{ error: string | null }>;
  signUpWithEmail: (email: string, password: string, name: string, termsAccepted: boolean) => Promise<{ error: string | null; message?: string }>;
  requestPasswordReset: (email: string) => Promise<{ error: string | null; message?: string }>;
  resendConfirmationEmail: (email: string) => Promise<{ error: string | null; message?: string }>;
  updatePassword: (newPassword: string) => Promise<{ error: string | null }>;
  changeOwnPassword: (currentPassword: string, newPassword: string) => Promise<{ error: string | null }>;
  saveDisplayName: (name: string) => Promise<{ error: string | null }>;
  updateNotificationPrefs: (enabled: boolean, thresholdUsd: number) => Promise<{ error: string | null }>;
  isSupabaseReady: boolean;
  apiKeys: ApiKey[];
  isApiKeysLoading: boolean;
  loadApiKeys: () => Promise<void>;
  createApiKey: (name: string, thinkingLevel?: string) => Promise<CreatedApiKey>;
  // Sets one key's thinking level ('sdk' or a tier name). Updates the row
  // at once and puts it back if the server refuses; throws so the page can say why.
  updateApiKeyThinkingLevel: (id: string, thinkingLevel: string) => Promise<void>;
  deleteApiKey: (id: string) => Promise<void>;
  requestLogs: RequestLog[];
  usageHistory: UsageDay[];
  usageByProduct: Record<string, StatsByProductEntry>;
  isStatsLoading: boolean;
  loadStats: () => Promise<void>;
  chatMessages: ChatMessage[];
  isGenerating: boolean;
  chatSessions: ChatSession[];
  activeSessionId: string | null;
  isSessionsLoading: boolean;
  isSessionUnresumable: boolean;
  isSessionLoading: boolean;
  sessionsError: boolean;
  sessionLoadError: string | null;
  loadChatSessions: () => Promise<void>;
  // Starts an empty conversation. Passing a model also selects it for that conversation.
  startNewChatSession: (model?: ModelId) => void;
  selectChatSession: (id: string) => Promise<void>;
  // rename/delete resolve to null on success, or a message the page shows.
  renameChatSession: (id: string, title: string) => Promise<string | null>;
  deleteChatSession: (id: string) => Promise<string | null>;
  // `images`: pictures attached to this message (each with its base64 `data` and a local `src` preview).
  sendChatMessage: (content: string, images?: ChatMessageImage[]) => Promise<void>;
  // The model the NEXT new conversation uses. Once a conversation exists it is
  // locked to its own model (see activeModel), so this only matters before the
  // first message.
  selectedModel: ModelId;
  setSelectedModel: (model: ModelId) => void;
  // The model of the conversation on screen: its own once it exists, else the
  // selected one.
  activeModel: ModelId;
  // Kael's reasoning_effort for new messages in the playground, for activeModel.
  // Each model keeps its own level and accepts only its own (see MODELS in
  // lib/api.ts). There is no "off": Kael always thinks.
  thinkingLevel: ThinkingLevel;
  setThinkingLevel: (level: ThinkingLevel) => void;
  retryChatMessage: (errorMessageId: string) => Promise<void>;
  clearChat: () => void;
  updateUserProfile: (updates: Partial<UserProfile>) => void;
  adminStats: AdminStats | null;
  adminUsers: AdminUserRecord[];
  isAdminDataLoading: boolean;
  loadAdminStats: () => Promise<void>;
  loadAdminUsers: () => Promise<void>;
  creditAdminUser: (userId: string, amountUsd: number) => Promise<CreditAdminUserResponse>;
  suspendAdminUser: (userId: string) => Promise<SuspendAdminUserResponse>;
  activateAdminUser: (userId: string) => Promise<ActivateAdminUserResponse>;
  runAdminReconcile: () => Promise<ReconcileAdminResponse>;
}

// Best-effort: after a password change succeeds, ask the backend to email the
// user a "your password was changed" notice. Never blocks, throws, or fails
// the password change itself.
async function sendPasswordChangedNotice(supabase: NonNullable<ReturnType<typeof getSupabase>>): Promise<void> {
  try {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) await notifyPasswordChangedApi(token);
  } catch {
    // ignore: the notice is a courtesy, not part of changing the password
  }
}

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const router = useRouter();
  const [isLoggedIn, setIsLoggedIn] = useState<boolean>(false);
  const [authChecked, setAuthChecked] = useState<boolean>(false);
  // onAuthStateChange fires once immediately with whatever session is
  // already in localStorage as soon as it's subscribed — on every page
  // load/refresh, not just on a real sign-in. Without this flag, that
  // first firing was indistinguishable from an actual "SIGNED_IN" login
  // event, so the code below force-navigated to /dashboard on every
  // refresh of every page. Only redirect once this has fired before.
  const hasHandledFirstAuthEvent = useRef(false);
  // Supabase's GoTrue client re-emits SIGNED_IN (with the same session)
  // whenever the tab/window regains focus or visibility — this is
  // documented client behavior, not a bug on their end (see
  // supabase/supabase-js#442). hasHandledFirstAuthEvent alone doesn't
  // catch this: it only guards the very first event, but a refocus
  // SIGNED_IN can fire long after that, indistinguishable from a real
  // login without tracking whether we already considered this session
  // signed in. Mirrors the last state *this listener* saw, updated
  // synchronously inside the callback (not via React state, which
  // batches/lags behind the closure here).
  const wasSignedInRef = useRef(false);
  // The manual getSession() check below and onAuthStateChange's own
  // first (synthetic) firing both observe the SAME starting session —
  // this was already true before this file's other fixes, not
  // introduced by them. Whichever of the two resolves first calls
  // loadUserData and flips this; the other then skips its own call
  // instead of re-running all five of loadUserData's backend requests
  // (fetchMe, fetchBilling, loadChatSessions, loadApiKeys, loadStats)
  // a second time for data that's already been requested. Only guards
  // this one "starting session" case — every later genuine sign-in
  // still calls loadUserData normally (see isFirstAuthEvent below).
  const hasDispatchedInitialLoad = useRef(false);
  // changeOwnPassword below re-verifies the current password via
  // signInWithPassword before actually changing it — that's a real
  // sign-in as far as Supabase is concerned, so it fires its own
  // SIGNED_IN event through the exact same listener a fresh login does.
  // wasSignedInRef above would likely already suppress the resulting
  // redirect too (the user is necessarily already signed in to reach
  // AccountPage at all), but changeOwnPassword doesn't rely on that
  // overlap holding — this flag ties the suppression directly to the
  // one call site that needs it, independent of tab-refocus detection
  // logic built for an unrelated reason.
  const suppressNextSignInRedirect = useRef(false);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null);
  const [billing, setBilling] = useState<BillingResponse | null>(null);
  const [billingLoading, setBillingLoading] = useState<boolean>(false);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [isApiKeysLoading, setIsApiKeysLoading] = useState<boolean>(false);
  // Real data from GET /api/stats (supabase_client.fetch_stats), loaded by
  // loadStats() below — starts empty, never with placeholder data. A
  // brand-new account will genuinely see an empty chart/table here until
  // it makes its first real request; that's correct, not a bug.
  const [requestLogs, setRequestLogs] = useState<RequestLog[]>([]);
  const [usageHistory, setUsageHistory] = useState<UsageDay[]>([]);
  const [usageByProduct, setUsageByProduct] = useState<Record<string, StatsByProductEntry>>({});
  const [isStatsLoading, setIsStatsLoading] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [selectedModel, setSelectedModelState] = useState<ModelId>(DEFAULT_MODEL);
  const [thinkingLevels, setThinkingLevelsState] = useState<ThinkingLevels>(defaultThinkingLevels);
  // Read after mount (not in the initial state) so server and client render
  // the same HTML.
  useEffect(() => {
    setSelectedModelState(readStoredModel());
    setThinkingLevelsState(readStoredThinkingLevels());
  }, []);
  const thinkingLevelsRef = useRef<ThinkingLevels>(thinkingLevels);
  thinkingLevelsRef.current = thinkingLevels;
  const setSelectedModel = useCallback((model: ModelId) => {
    if (!isModelId(model)) return;
    setSelectedModelState(model);
    try {
      localStorage.setItem(SELECTED_MODEL_STORAGE_KEY, model);
    } catch {
      // Not persisted; still applies for this visit.
    }
  }, []);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [isSessionsLoading, setIsSessionsLoading] = useState<boolean>(false);
  const [isSessionUnresumable, setIsSessionUnresumable] = useState<boolean>(false);
  const [isSessionLoading, setIsSessionLoading] = useState<boolean>(false);
  const [sessionsError, setSessionsError] = useState<boolean>(false);
  // The model of the open conversation, set when it is loaded or created. The
  // sidebar list carries it too; this covers the moment before the list arrives
  // (opening /playground/<id> directly), so a message is never sent with the
  // other model's thinking level.
  const [activeSessionModel, setActiveSessionModel] = useState<ModelId | null>(null);
  // A conversation is locked to the model it started with (the backend refuses
  // to continue it on another). Before the first message there is no
  // conversation yet, so the selected model decides.
  const listedModel = chatSessions.find((s) => s.id === activeSessionId)?.model;
  const activeModel: ModelId = !activeSessionId
    ? selectedModel
    : isModelId(listedModel)
      ? listedModel
      : activeSessionModel ?? selectedModel;
  const thinkingLevel: ThinkingLevel = thinkingLevels[activeModel];
  // Sets the level for the model on screen. A level the model does not accept is
  // ignored (the backend would answer 400).
  const setThinkingLevel = useCallback(
    (level: ThinkingLevel) => {
      const info = MODELS.find((m) => m.id === activeModel);
      if (!info || !info.levels.includes(level)) return;
      setThinkingLevelsState((prev) => {
        const next = { ...prev, [activeModel]: level };
        try {
          localStorage.setItem(THINKING_LEVELS_STORAGE_KEY, JSON.stringify(next));
        } catch {
          // Not persisted; still applies for this visit.
        }
        return next;
      });
    },
    [activeModel]
  );
  // Bumped by every session switch / new chat so a slow response for a chat
  // the user already left can't overwrite the one they are looking at.
  const sessionRequestRef = useRef(0);
  // Back to an empty playground conversation. Bumping sessionRequestRef also
  // stops any reply being followed, and isGenerating is cleared so a sign-out
  // in the middle of a reply cannot leave the composer locked for the next
  // person who signs in. (Every setter used here is stable.)
  const resetPlaygroundState = useCallback(() => {
    sessionRequestRef.current += 1;
    setActiveSessionId(null);
    setActiveSessionModel(null);
    setIsSessionUnresumable(false);
    setIsSessionLoading(false);
    setSessionLoadError(null);
    setIsGenerating(false);
    setChatMessages([makeWelcomeMessage()]);
  }, []);
  // Set when a specific /playground/<sessionId> URL couldn't be loaded
  // (deleted, someone else's, or a transient failure) so the page can show
  // a clear notice instead of silently leaving stale or blank messages
  // under a URL that doesn't actually resolve to anything.
  const [sessionLoadError, setSessionLoadError] = useState<string | null>(null);
  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [adminUsers, setAdminUsers] = useState<AdminUserRecord[]>([]);
  const [isAdminDataLoading, setIsAdminDataLoading] = useState<boolean>(false);

  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([makeWelcomeMessage()]);

  // Fetch public config on mount
  useEffect(() => {
    fetchPublicConfig()
      .then((cfg) => {
        setPublicConfig(cfg);
      })
      .catch((err) => {
        console.warn('Failed to fetch public config from backend:', err);
      });
  }, []);

  const loadApiKeys = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setIsApiKeysLoading(true);
    try {
      const res = await listApiKeysApi(session.access_token);
      const mapped: ApiKey[] = (res.keys || []).map((k) => ({
        id: k.id,
        name: k.name,
        key: `${k.prefix}••••••••••••••••••••••••`,
        prefix: k.prefix,
        createdAt: k.created_at ? new Date(k.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : '',
        lastUsedAt: k.last_used_at ? new Date(k.last_used_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : 'Never',
        active: !k.revoked,
        thinkingLevel: k.thinking_level || 'sdk',
      }));
      setApiKeys(mapped);
    } catch (err) {
      console.warn('Failed to load API keys:', err);
    } finally {
      setIsApiKeysLoading(false);
    }
  }, []);

  const loadStats = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setIsStatsLoading(true);
    try {
      const stats = await fetchStats(session.access_token);
      if (stats.enabled) {
        setUsageHistory(
          (stats.daily || []).map((d) => ({
            date: d.date,
            inputTokens: d.input_tokens,
            cachedTokens: d.cached_tokens,
            outputTokens: d.output_tokens,
            totalRequests: d.total_requests,
            costDollars: d.cost_usd,
            avgLatencyMs: d.avg_latency_ms,
          }))
        );
        setRequestLogs(
          (stats.recent || []).map((r) => ({
            id: r.id,
            timestamp: r.timestamp,
            endpoint: r.endpoint,
            model: r.model,
            status: r.status,
            tokens: r.tokens,
            cacheHit: r.cache_hit,
            latency: r.latency_ms,
            cost: r.cost_usd,
          }))
        );
        setUsageByProduct(stats.by_product || {});
      }
    } catch (err) {
      console.warn('Failed to load usage stats:', err);
    } finally {
      setIsStatsLoading(false);
    }
  }, []);

  const loadChatSessions = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setIsSessionsLoading(true);
    try {
      const res = await listChatSessions(session.access_token);
      setChatSessions(res.sessions || []);
      setSessionsError(false);
    } catch (err) {
      console.warn('Failed to load playground conversations:', err);
      setSessionsError(true);
    } finally {
      setIsSessionsLoading(false);
    }
  }, []);

  // Sync user profile & billing data from backend given a valid Supabase token
  const loadUserData = useCallback(async (token: string, sessionUser: any) => {
    setBillingLoading(true);

    let meData: { id: string; email?: string; is_admin?: boolean } | null = null;
    let billingData: BillingResponse | null = null;

    try {
      meData = await fetchMe(token);
    } catch (err: any) {
      if ((err instanceof ApiError && err.code === 'account_suspended') || err?.code === 'account_suspended') {
        const supabase = getSupabase();
        if (supabase) {
          await supabase.auth.signOut();
        }
        setUser(null);
        setIsLoggedIn(false);
        setBilling(null);
        setBillingLoading(false);
        setApiKeys([]);
        setChatSessions([]);
        setActiveSessionId(null);
        setIsSessionUnresumable(false);
        alert('This account has been suspended.');
        return;
      }
      console.warn('Failed to fetch /api/me:', err);
    }

    try {
      billingData = await fetchBilling(token);
      setBilling(billingData);
    } catch (err: any) {
      if ((err instanceof ApiError && err.code === 'account_suspended') || err?.code === 'account_suspended') {
        const supabase = getSupabase();
        if (supabase) {
          await supabase.auth.signOut();
        }
        setUser(null);
        setIsLoggedIn(false);
        setBilling(null);
        setBillingLoading(false);
        setApiKeys([]);
        setChatSessions([]);
        setActiveSessionId(null);
        setIsSessionUnresumable(false);
        alert('This account has been suspended.');
        return;
      }
      console.warn('Failed to fetch /api/billing:', err);
      setBilling(null);
    } finally {
      setBillingLoading(false);
    }

    const rawBalance = billingData?.balance_usd;
    const balanceNumber = rawBalance != null ? parseFloat(rawBalance) : null;

    const rawSpend = billingData?.total_spent_usd;
    const spendNumber = rawSpend != null ? parseFloat(rawSpend) : null;

    const profile: UserProfile = buildProfileFromSession(sessionUser, {
      id: meData?.id,
      email: meData?.email,
      role: meData?.is_admin ? 'admin' : 'user',
      creditBalance: balanceNumber != null && !isNaN(balanceNumber) ? balanceNumber : null,
      monthlySpend: spendNumber != null && !isNaN(spendNumber) ? spendNumber : null,
    });

    setUser(profile);
    setIsLoggedIn(true);

    // If an OAuth sign-in just completed with the Terms/Privacy
    // checkbox checked beforehand (see signInWithGitHub/signInWithGoogle
    // above), record that acceptance now that we have a verified
    // session token to authenticate the write with. Fires at most once
    // per flag — cleared immediately regardless of outcome, and the
    // backend is idempotent besides (has_legal_acceptance), so this is
    // safe even if loadUserData ends up running again before the flag
    // is cleared (e.g. a second SIGNED_IN event).
    try {
      if (window.localStorage.getItem(PENDING_OAUTH_CONSENT_KEY)) {
        window.localStorage.removeItem(PENDING_OAUTH_CONSENT_KEY);
        recordOAuthConsentApi(token).catch((err) => {
          console.warn('Failed to record OAuth consent:', err);
        });
      }
    } catch { /* private browsing, etc. — non-fatal */ }

    // Fetch user's chat sessions, API keys, and real usage stats
    loadChatSessions();
    loadApiKeys();
    loadStats();
  }, [loadChatSessions, loadApiKeys, loadStats]);

  const refreshBilling = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setBillingLoading(true);
    try {
      const billingData = await fetchBilling(session.access_token);
      setBilling(billingData);
      const balanceNumber = billingData.balance_usd != null ? parseFloat(billingData.balance_usd) : null;
      const spendNumber = billingData.total_spent_usd != null ? parseFloat(billingData.total_spent_usd) : null;

      setUser((prev) =>
        prev
          ? {
              ...prev,
              creditBalance: balanceNumber != null && !isNaN(balanceNumber) ? balanceNumber : prev.creditBalance,
              monthlySpend: spendNumber != null && !isNaN(spendNumber) ? spendNumber : prev.monthlySpend,
            }
          : null
      );
    } catch (err) {
      console.warn('Failed to refresh billing:', err);
    } finally {
      setBillingLoading(false);
    }
  }, []);

  // Listen to Supabase Auth
  useEffect(() => {
    const supabase = getSupabase();
    if (supabase) {
      // Check existing session
      supabase.auth.getSession().then(({ data: { session } }) => {
        if (session?.user && session?.access_token) {
          // Flip isLoggedIn immediately from the session alone — this is
          // a fast, local (localStorage) check. loadUserData below still
          // runs to hydrate the profile/billing/etc., but route guards
          // like RequireAuth only need to know "is there a session,"
          // not "has the backend profile finished loading." Gating
          // isLoggedIn on loadUserData (which awaits two sequential
          // backend calls) was the root cause of authenticated users
          // being bounced to /login for however long those calls took.
          setIsLoggedIn(true);
          wasSignedInRef.current = true;
          if (!hasDispatchedInitialLoad.current) {
            hasDispatchedInitialLoad.current = true;
            loadUserData(session.access_token, session.user);
          }
        } else if (session?.user) {
          wasSignedInRef.current = true;
          setUser(buildProfileFromSession(session.user));
          setIsLoggedIn(true);
        }
      }).finally(() => setAuthChecked(true));

      // Listen for auth changes
      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        // Capture "was this the very first time this listener has fired"
        // before flipping the flag, so everything below can tell a real
        // login apart from Supabase just reporting the session it found
        // in localStorage on this page load.
        const isFirstAuthEvent = !hasHandledFirstAuthEvent.current;
        hasHandledFirstAuthEvent.current = true;
        // Captured before this event updates it — tells us whether the
        // *previous* event this listener saw already had a session, so
        // we can tell a genuine new sign-in from Supabase re-announcing
        // one we already knew about (tab/screen refocus).
        const wasSignedIn = wasSignedInRef.current;
        const suppressRedirect = suppressNextSignInRedirect.current;
        suppressNextSignInRedirect.current = false;

        if (_event === 'PASSWORD_RECOVERY') {
          // A clicked password-reset link lands here with a temporary
          // session already set — route to the reset form instead of
          // the normal dashboard redirect below. Not treated as a full
          // sign-in (isLoggedIn stays false) since the user hasn't
          // chosen a new password yet.
          router.push('/reset-password');
          return;
        }
        if (session?.user && session?.access_token) {
          wasSignedInRef.current = true;
          // Flip immediately — see the matching comment on the initial
          // getSession() check above. Don't make route guards wait on
          // loadUserData's network calls.
          setIsLoggedIn(true);
          // Skip only when this is the very first event AND the manual
          // getSession() check above already dispatched loadUserData
          // for this same starting session — see hasDispatchedInitialLoad's
          // comment. Any later, genuine sign-in (isFirstAuthEvent false)
          // always loads fresh, regardless of this flag.
          if (!(isFirstAuthEvent && hasDispatchedInitialLoad.current)) {
            hasDispatchedInitialLoad.current = true;
            loadUserData(session.access_token, session.user);
          }
          // Only redirect to /dashboard on a REAL new sign-in: not the
          // first event this listener ever sees (page load/refresh with
          // an existing session), not a session we already considered
          // signed in (tab/window refocus re-emits SIGNED_IN with the
          // *same* session — see supabase/supabase-js#442 — which used
          // to force-navigate a user on e.g. /keys or /usage back to
          // /dashboard for no reason every time they returned to the
          // tab), and not changeOwnPassword's own re-verification
          // sign-in (see suppressNextSignInRedirect above).
          if (_event === 'SIGNED_IN' && !isFirstAuthEvent && !wasSignedIn && !suppressRedirect) {
            router.push('/dashboard');
          }
        } else if (session?.user) {
          wasSignedInRef.current = true;
          setUser(buildProfileFromSession(session.user));
          setIsLoggedIn(true);
          if (_event === 'SIGNED_IN' && !isFirstAuthEvent && !wasSignedIn && !suppressRedirect) {
            router.push('/dashboard');
          }
        } else if (_event === 'SIGNED_OUT') {
          wasSignedInRef.current = false;
          setUser(null);
          setIsLoggedIn(false);
          setBilling(null);
          setBillingLoading(false);
          setApiKeys([]);
          setChatSessions([]);
          resetPlaygroundState();
          // Only navigate away on a real logout action. On page load for a
          // visitor who was never logged in, this same branch fires as the
          // initial "no session found" report — without this check that
          // used to yank a logged-out visitor on e.g. /docs back to '/'.
          if (!isFirstAuthEvent) {
            router.push('/');
          }
        }
      });

      return () => {
        subscription.unsubscribe();
      };
    } else {
      // No Supabase client (env vars missing) — nothing to wait on, so
      // don't leave route guards stuck showing a loading spinner forever.
      setAuthChecked(true);
    }
  }, [loadUserData]);

  const login = (email?: string, name?: string) => {
    setIsLoggedIn(true);
    const userEmail = email || 'developer@quancis.space';
    const newUser: UserProfile = {
      id: 'usr_quan_' + Math.random().toString(36).substring(2, 8),
      name: name || 'Developer Account',
      email: userEmail,
      avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
      tier: 'Scale',
      role: 'user',
      creditBalance: null,
      monthlySpend: null,
      createdAt: '2026-03-01',
      provider: 'email',
      lowBalanceAlertEnabled: false,
      lowBalanceAlertThresholdUsd: 10,
    };
    setUser(newUser);
    router.push('/dashboard');
  };

  // consentGiven reflects whether the Terms/Privacy checkbox was
  // checked on LoginPage at the moment this was called — the button is
  // disabled otherwise, but this is checked again here too rather than
  // trusted blindly, since it's what decides whether the pending-consent
  // flag gets set at all. See PENDING_OAUTH_CONSENT_KEY above and
  // loadUserData below for what happens with it after the redirect
  // completes.
  const signInWithGitHub = async (consentGiven: boolean): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (supabase) {
      if (consentGiven) {
        try { window.localStorage.setItem(PENDING_OAUTH_CONSENT_KEY, '1'); } catch { /* private browsing, etc. — non-fatal, just means consent won't be recorded this time */ }
      }
      const redirectTo = window.location.origin;
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'github',
        options: {
          redirectTo,
          // Without this, a GitHub account with its email set to
          // private can come back from GoTrue with no email at all —
          // this is what previously let sessionUser.email be
          // undefined and fall through to a fake-looking placeholder.
          // 'user:email' is exactly the scope GitHub's own docs say is
          // required to read a private primary email.
          scopes: 'read:user user:email',
        },
      });
      if (error) {
        return { error: error.message };
      }
      return { error: null };
    } else {
      return { 
        error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings to authenticate with GitHub.' 
      };
    }
  };

  // Mirrors signInWithGitHub exactly — same Supabase OAuth redirect flow,
  // same onAuthStateChange listener above picks up the resulting session
  // generically (it doesn't care which provider issued it), so no other
  // code path needs to know Google exists. All the actual setup lives in
  // the Google Cloud Console (OAuth client) and the Supabase Dashboard
  // (Authentication → Providers → Google) — see chat for the full steps.
  const signInWithGoogle = async (consentGiven: boolean): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (supabase) {
      if (consentGiven) {
        try { window.localStorage.setItem(PENDING_OAUTH_CONSENT_KEY, '1'); } catch { /* non-fatal */ }
      }
      const redirectTo = window.location.origin;
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo,
          queryParams: {
            // Google-specific: ensures the consent screen is always shown
            // and a refresh token is issued on first authorization, which
            // Supabase needs to keep the session alive without forcing a
            // re-consent on every login.
            access_type: 'offline',
            prompt: 'consent',
          },
        },
      });
      if (error) {
        return { error: error.message };
      }
      return { error: null };
    } else {
      return {
        error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings to authenticate with Google.'
      };
    }
  };

  // Sign-in itself needs no backend route — Supabase verifies the
  // password directly against the anon key, same trust boundary as
  // signInWithGitHub above. A successful call fires the
  // onAuthStateChange listener below (SIGNED_IN) exactly like OAuth
  // does, which is what actually loads the profile/billing/session data
  // and routes to the dashboard — nothing further needed here.
  const signInWithEmail = async (email: string, password: string): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings.' };
    }
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) return { error: error.message };
    return { error: null };
  };

  // Account creation itself goes through the backend (POST
  // /api/auth/signup), not supabase.auth.signUp() directly — the
  // backend owns the confirmation email via Resend instead of
  // Supabase's own rate-limited sender. See app/auth_email.py. No
  // session is created by this call; the user isn't signed in until
  // they click the emailed confirmation link.
  //
  // termsAccepted is sent through and enforced server-side (see
  // auth_email.signup's own check) — the backend is the actual source
  // of truth for consent, not this checkbox alone. A true value here
  // also causes the backend to write a durable acceptance record (see
  // supabase_client.record_legal_acceptance).
  const signUpWithEmail = async (email: string, password: string, name: string, termsAccepted: boolean): Promise<{ error: string | null; message?: string }> => {
    try {
      const res = await signUpEmailApi(email, password, name, termsAccepted);
      return { error: null, message: res.message };
    } catch (err: any) {
      return { error: err?.message || 'Failed to sign up. Please try again.' };
    }
  };

  const requestPasswordReset = async (email: string): Promise<{ error: string | null; message?: string }> => {
    try {
      const res = await forgotPasswordApi(email);
      return { error: null, message: res.message };
    } catch (err: any) {
      return { error: err?.message || 'Failed to send reset email. Please try again.' };
    }
  };

  const resendConfirmationEmail = async (email: string): Promise<{ error: string | null; message?: string }> => {
    try {
      const res = await resendConfirmationApi(email);
      return { error: null, message: res.message };
    } catch (err: any) {
      return { error: err?.message || 'Failed to resend the confirmation email. Please try again.' };
    }
  };

  // Used by ResetPasswordPage once the user has landed there via a
  // clicked recovery-email link (see the PASSWORD_RECOVERY branch in
  // the onAuthStateChange listener below) — Supabase's recovery link
  // already grants a temporary session that updateUser can act on.
  const updatePassword = async (newPassword: string): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings.' };
    }
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { error: error.message };
    void sendPasswordChangedNotice(supabase);
    return { error: null };
  };

  // Used by AccountPage's Security tab — unlike updatePassword above
  // (which trusts a Supabase password-recovery link's own temporary
  // session), this is for an already-logged-in user proactively
  // changing their password, so it re-verifies the current password
  // first via signInWithPassword. Supabase's updateUser() would
  // otherwise accept a new password from anyone holding a valid access
  // token, with no proof they know the current one. Only meaningful for
  // 'email' provider accounts — see UserProfile.provider; Google/GitHub
  // accounts have no password on our side to verify or change, and
  // AccountPage doesn't render this form for them.
  const changeOwnPassword = async (
    currentPassword: string,
    newPassword: string
  ): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings.' };
    }
    if (!user?.email) {
      return { error: 'No email on file for this account.' };
    }
    // signInWithPassword below is a real sign-in as far as Supabase is
    // concerned and fires its own SIGNED_IN event — see
    // suppressNextSignInRedirect's declaration above for why this has
    // to be set first.
    suppressNextSignInRedirect.current = true;
    const { error: verifyError } = await supabase.auth.signInWithPassword({
      email: user.email,
      password: currentPassword,
    });
    if (verifyError) {
      suppressNextSignInRedirect.current = false;
      return { error: 'Current password is incorrect.' };
    }
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) return { error: error.message };
    void sendPasswordChangedNotice(supabase);
    return { error: null };
  };

  // Persists the display name for real via Supabase Auth's own
  // user_metadata (self-editable by the signed-in user through the anon
  // key + their session — no backend route needed for this). Replaces
  // the old AccountPage behavior of only writing to localStorage, which
  // never survived a new device or a cleared cache. Email is
  // deliberately not editable here or anywhere else in the app — see
  // buildProfileFromSession's docstring above for why it's always
  // sourced from Supabase/GoTrue directly instead.
  const saveDisplayName = async (name: string): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings.' };
    }
    const trimmed = name.trim();
    if (!trimmed) {
      return { error: 'Name cannot be empty.' };
    }
    // supabase.auth.updateUser({ data }) replaces user_metadata wholesale
    // rather than merging it — a documented GoTrue behavior, not a
    // Supabase-JS quirk (see supabase/supabase-py#1644), and the exact
    // hazard this backend's own PATCH /api/theme already guards against
    // (main.py: `merged_metadata = {**(user.get("user_metadata") or {}), "theme": theme}`).
    // Skipping this spread would mean saving your name here silently
    // wipes out the notification prefs below, and vice versa.
    const { data: { session } } = await supabase.auth.getSession();
    const existingMeta = session?.user?.user_metadata || {};
    const { error } = await supabase.auth.updateUser({ data: { ...existingMeta, name: trimmed } });
    if (error) return { error: error.message };
    updateUserProfile({ name: trimmed });
    return { error: null };
  };

  // Same pattern as saveDisplayName above — self-editable user_metadata,
  // no backend route to write it. Read back by the separate
  // app/jobs/low_balance_alerts.py cron job (not this web service) to
  // decide who to email and at what threshold; see that file for the
  // actual delivery side of this preference.
  const updateNotificationPrefs = async (
    enabled: boolean,
    thresholdUsd: number
  ): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase credentials are missing. Please configure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in Settings.' };
    }
    if (!Number.isFinite(thresholdUsd) || thresholdUsd < 0) {
      return { error: 'Enter a valid, non-negative alert threshold.' };
    }
    // See saveDisplayName's comment above — same wholesale-replace
    // hazard, same fix (read current user_metadata, spread it, then
    // override just these two keys).
    const { data: { session } } = await supabase.auth.getSession();
    const existingMeta = session?.user?.user_metadata || {};
    const { error } = await supabase.auth.updateUser({
      data: {
        ...existingMeta,
        low_balance_alert_enabled: enabled,
        low_balance_alert_threshold_usd: thresholdUsd,
      },
    });
    if (error) return { error: error.message };
    updateUserProfile({ lowBalanceAlertEnabled: enabled, lowBalanceAlertThresholdUsd: thresholdUsd });
    return { error: null };
  };

  const logout = async () => {
    const supabase = getSupabase();
    if (supabase) {
      await supabase.auth.signOut();
    }
    setIsLoggedIn(false);
    setUser(null);
    setBilling(null);
    setBillingLoading(false);
    setApiKeys([]);
    setChatSessions([]);
    resetPlaygroundState();
    router.push('/');
  };

  // Permanently deletes the signed-in account (DELETE /api/account, see
  // backend app/account.py), then signs out here and returns to the home page.
  // Errors come back as text for the Account page to show; nothing is signed out
  // unless the backend confirmed the deletion. The Supabase user no longer exists
  // after that, so the local sign-out only clears this browser's session (scope
  // 'local' makes no server call that could fail on a user that is already gone).
  const deleteAccount = async (confirm: string): Promise<{ error: string | null }> => {
    const supabase = getSupabase();
    if (!supabase) {
      return { error: 'Supabase client not initialized' };
    }
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      return { error: 'You must be signed in to delete your account.' };
    }
    try {
      await deleteAccountApi(session.access_token, confirm);
    } catch (e) {
      return { error: e instanceof Error && e.message ? e.message : 'We could not delete your account. Please try again.' };
    }
    try {
      await supabase.auth.signOut({ scope: 'local' });
    } catch {
      // The account is already gone; a failed local sign-out must not hide that.
    }
    setIsLoggedIn(false);
    setUser(null);
    setBilling(null);
    setBillingLoading(false);
    setApiKeys([]);
    setChatSessions([]);
    resetPlaygroundState();
    router.push('/');
    return { error: null };
  };

  const createApiKey = async (name: string, thinkingLevel: string = 'sdk'): Promise<CreatedApiKey> => {
    const supabase = getSupabase();
    if (!supabase) {
      throw new Error('Supabase client not initialized');
    }
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) {
      throw new Error('You must be signed in to create an API key');
    }

    const created = await createApiKeyApi(session.access_token, name, thinkingLevel);
    const newKey: ApiKey = {
      id: created.id,
      name: created.name,
      key: `${created.prefix}••••••••••••••••••••••••`,
      prefix: created.prefix,
      createdAt: created.created_at ? new Date(created.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : 'Just now',
      lastUsedAt: 'Never',
      active: !created.revoked,
      thinkingLevel: created.thinking_level || 'sdk',
    };
    setApiKeys((prev) => [newKey, ...prev.filter((k) => k.id !== newKey.id)]);
    return created;
  };

  const updateApiKeyThinkingLevel = async (id: string, thinkingLevel: string): Promise<void> => {
    const supabase = getSupabase();
    if (!supabase) throw new Error('Supabase client not initialized');
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('You must be signed in to change this setting');

    const previous = apiKeys.find((k) => k.id === id)?.thinkingLevel ?? 'sdk';
    const setLevel = (level: string) =>
      setApiKeys((prev) => prev.map((k) => (k.id === id ? { ...k, thinkingLevel: level } : k)));

    setLevel(thinkingLevel); // show the new choice immediately
    try {
      const res = await updateApiKeyThinkingLevelApi(session.access_token, id, thinkingLevel);
      setLevel(res.thinking_level || 'sdk'); // what the server actually stored
    } catch (err) {
      setLevel(previous);
      console.warn('Failed to update thinking level:', err);
      throw err;
    }
  };

  const deleteApiKey = async (id: string): Promise<void> => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    try {
      await deleteApiKeyApi(session.access_token, id);
      setApiKeys((prev) => prev.filter((k) => k.id !== id));
    } catch (err) {
      console.warn('Failed to delete API key:', err);
      throw err;
    }
  };

  const updateUserProfile = (updates: Partial<UserProfile>) => {
    if (user) {
      const updated = { ...user, ...updates };
      setUser(updated);
      localStorage.setItem('quan_user_session', JSON.stringify(updated));
    }
  };

  const clearChat = () => {
    setChatMessages([]);
  };

  const startNewChatSession = useCallback((model?: ModelId) => {
    sessionRequestRef.current += 1;
    if (model) setSelectedModel(model);
    setActiveSessionId(null);
    setActiveSessionModel(null);
    setIsSessionUnresumable(false);
    setIsSessionLoading(false);
    setSessionLoadError(null);
    setChatMessages([makeWelcomeMessage()]);
  }, [setSelectedModel]);

  // Keeps a reply that is still running on the server in view: after a reload,
  // or after the connection to a message being sent dropped. The reply keeps
  // generating on the server whether or not this page is connected, so this
  // only watches (GET /api/chat/sessions/{id} -> `pending`) and swaps in the
  // saved result when it lands. Stops when the user moves to another chat
  // (sessionRequestRef changes) or after FOLLOW_MAX_MS.
  //
  // `sent` is set when the page itself sent the message and lost the
  // connection: if the server then has neither a running reply nor the saved
  // exchange, the message never arrived and the user gets a Retry.
  const followPendingReply = useCallback(
    async (sessionId: string, requestId: number, sent?: { text: string; at: number }) => {
      const deadline = Date.now() + FOLLOW_MAX_MS;
      const notice = (err: string) =>
        setChatMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.role === 'assistant') {
            return prev.map((m) => (m.id === last.id ? { ...m, error: err, thinkingLabel: undefined } : m));
          }
          return [
            ...prev,
            { id: 'msg_err_' + Date.now(), role: 'assistant', content: '', error: err, timestamp: clockTime(), model: last?.model ?? DEFAULT_MODEL },
          ];
        });
      try {
        while (requestId === sessionRequestRef.current && Date.now() < deadline) {
          const supabase = getSupabase();
          const auth = supabase ? await supabase.auth.getSession() : null;
          const token = auth?.data?.session?.access_token;
          let detail: ChatSessionDetail | null = null;
          if (token) {
            try {
              detail = await getChatSession(token, sessionId);
            } catch (err) {
              if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
                if (requestId === sessionRequestRef.current) {
                  notice(err.status === 404 ? "This chat doesn't exist or isn't yours." : 'This chat can no longer be continued.');
                }
                return;
              }
              // Offline, a restart, a 503: just try again shortly.
              detail = null;
            }
          }
          if (requestId !== sessionRequestRef.current) return;

          if (detail) {
            const resumable = detail.resumable !== false;
            const label = modelLabelForSession(detail.model, resumable);
            const pending = detail.pending;
            if (pending && pending.status === 'running') {
              setChatMessages(mapSessionDetail(detail, label));
            } else if (pending && pending.status === 'error') {
              setChatMessages(mapSessionDetail(detail, label));
              return;
            } else {
              // Nothing running any more. If we are waiting on a message this
              // page sent, make sure it actually made it.
              const msgs = detail.messages || [];
              const delivered =
                !sent ||
                msgs.some(
                  (m, i) =>
                    m.role === 'user' &&
                    m.content === sent.text &&
                    msgs[i + 1]?.role === 'assistant' &&
                    (!m.created_at || Date.parse(m.created_at) >= sent.at - 5 * 60 * 1000)
                );
              if (delivered) {
                setChatMessages(mapSessionDetail(detail, label));
                refreshBilling().catch(() => {});
                loadChatSessions().catch(() => {});
              } else {
                notice("Your message didn't reach Quancis. Please try again.");
              }
              return;
            }
          }
          await waitOrWake(FOLLOW_POLL_MS);
        }
        if (requestId === sessionRequestRef.current) {
          notice('This reply is taking longer than expected. Reload the page to check on it.');
        }
      } finally {
        if (requestId === sessionRequestRef.current) setIsGenerating(false);
      }
    },
    // refreshBilling / loadChatSessions are stable useCallbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const selectChatSession = useCallback(async (sessionId: string) => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    const requestId = ++sessionRequestRef.current;
    setActiveSessionId(sessionId);
    setIsSessionUnresumable(false);
    setSessionLoadError(null);
    setIsSessionLoading(true);
    setIsGenerating(false);
    // Clear immediately rather than leaving the previous session's messages
    // on screen while this one loads — without this, switching sessions on
    // a slow connection briefly shows one conversation's content under
    // another conversation's URL.
    setChatMessages([]);
    let follow = false;
    try {
      const detail = await getChatSession(session.access_token, sessionId);
      if (requestId !== sessionRequestRef.current) return; // user already moved on
      const resumable = detail.resumable !== false;
      const modelLabel = modelLabelForSession(detail.model, resumable);
      setActiveSessionModel(isModelId(detail.model) ? detail.model : null);
      setChatMessages(mapSessionDetail(detail, modelLabel));
      // The backend says up front whether this chat can be continued, so the
      // input is locked immediately instead of after a failed send.
      setIsSessionUnresumable(!resumable);
      // A reply that was still being generated when the page was last open
      // (offline, reload, another tab): keep it in view until it lands.
      if (detail.pending?.status === 'running') {
        follow = true;
        setIsGenerating(true);
      }
    } catch (err: any) {
      if (requestId !== sessionRequestRef.current) return;
      console.warn('Failed to fetch session history:', err);
      if (err instanceof ApiError && err.status === 409) {
        setIsSessionUnresumable(true);
      } else if (err instanceof ApiError && err.status === 404) {
        setSessionLoadError("This chat doesn't exist or isn't yours.");
      } else {
        setSessionLoadError("Couldn't load this conversation. Please try again.");
      }
    } finally {
      if (requestId === sessionRequestRef.current) setIsSessionLoading(false);
    }
    if (follow) void followPendingReply(sessionId, requestId);
  }, [followPendingReply]);

  const renameChatSession = useCallback(async (id: string, title: string): Promise<string | null> => {
    const supabase = getSupabase();
    if (!supabase) return "Couldn't rename this conversation.";
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return 'Please sign in again.';

    try {
      const res = await renameChatSessionApi(session.access_token, id, title);
      const saved = res.title ?? title;
      setChatSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: saved } : s))
      );
      return null;
    } catch (err) {
      console.warn('Failed to rename playground conversation:', err);
      return err instanceof ApiError && err.message ? err.message : "Couldn't rename this conversation. Please try again.";
    }
  }, []);

  const deleteChatSession = useCallback(async (id: string): Promise<string | null> => {
    const supabase = getSupabase();
    if (!supabase) return "Couldn't delete this conversation.";
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return 'Please sign in again.';

    try {
      await deleteChatSessionApi(session.access_token, id);
      setChatSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        sessionRequestRef.current += 1;
        setActiveSessionId(null);
        setIsSessionUnresumable(false);
        setIsSessionLoading(false);
        setSessionLoadError(null);
        setChatMessages([makeWelcomeMessage()]);
        // The URL was /playground/<id> for the conversation we just
        // deleted — send it back to the bare playground so it doesn't
        // keep pointing at something that no longer exists.
        router.push('/playground');
      }
      return null;
    } catch (err) {
      console.warn('Failed to delete playground conversation:', err);
      return err instanceof ApiError && err.message ? err.message : "Couldn't delete this conversation. Please try again.";
    }
  }, [activeSessionId, router]);

  const sendChatMessage = async (content: string, images?: ChatMessageImage[]) => {
    const text = content.trim();
    // A message may be only pictures (text optional), but never empty.
    const attached = (images ?? []).filter((i): i is ChatMessageImage & { data: string } => typeof i.data === 'string' && i.data.length > 0);
    if ((!text && attached.length === 0) || isGenerating || isSessionUnresumable) return;

    const supabase = getSupabase();
    const sessionRes = supabase ? await supabase.auth.getSession() : null;
    const session = sessionRes?.data?.session;

    // The conversation's own model once it exists (the backend refuses to
    // continue it on another), else the one selected for a new conversation.
    // Every send below uses this model and ITS thinking level.
    const modelName: ModelId = activeModel;

    if (!session?.user || !session.access_token) {
      setChatMessages((prev) => [
        ...prev,
        {
          id: 'msg_err_' + Date.now(),
          role: 'assistant',
          content: '',
          error: 'Please sign in to use the Playground.',
          timestamp: clockTime(),
          model: modelName,
        },
      ]);
      return;
    }

    const stamp = Date.now();
    const userMsg: ChatMessage = {
      id: 'msg_' + stamp,
      role: 'user',
      content: text,
      timestamp: clockTime(),
      model: modelName,
      ...(attached.length > 0 ? { images: attached } : {}),
    };

    setChatMessages((prev) => [...prev, userMsg]);
    setIsGenerating(true);

    let currentSessionId = activeSessionId;
    let createdHere = false;

    // If no active session, create one first
    if (!currentSessionId) {
      try {
        const created = await createChatSession(session.access_token, modelName);
        currentSessionId = created.id;
        createdHere = true;
        setActiveSessionId(created.id);
        setActiveSessionModel(modelName);
        setIsSessionUnresumable(false);
        setSessionLoadError(null);
        setChatSessions((prev) => [created, ...prev.filter((s) => s.id !== created.id)]);
        // Give the new conversation its own URL now that it exists, rather
        // than leaving the address bar on the bare /playground while real
        // content accumulates underneath it. `replace`, not `push`: the bare
        // page was an empty shell, so Back shouldn't return to it.
        router.replace(playgroundSessionPath(created.id));
      } catch (err: any) {
        setIsGenerating(false);
        const errMsg = err instanceof ApiError ? err.message : "Couldn't reach Quancis, please try again.";
        setChatMessages((prev) => [
          ...prev,
          {
            id: 'msg_err_' + (stamp + 1),
            role: 'assistant',
            content: '',
            error: `Couldn't start a new conversation: ${errMsg}`,
            timestamp: clockTime(),
            model: modelName,
          },
        ]);
        return;
      }
    }

    const assistantMsgId = 'msg_asst_' + stamp;
    setChatMessages((prev) => [
      ...prev,
      {
        id: assistantMsgId,
        role: 'assistant',
        content: '',
        timestamp: clockTime(),
        model: modelName,
      },
    ]);

    const startTime = performance.now();
    let following = false;

    // Tokens arrive many times a second; re-rendering (and re-parsing the
    // markdown of) the whole message for each one gets slow on long replies.
    // They are buffered and flushed ~25 times a second instead. A timer, not
    // requestAnimationFrame, so a reply keeps filling in a background tab.
    let pendingDelta = '';
    let flushTimer: ReturnType<typeof setTimeout> | null = null;
    const flushTokens = () => {
      if (flushTimer !== null) {
        clearTimeout(flushTimer);
        flushTimer = null;
      }
      if (!pendingDelta) return;
      const delta = pendingDelta;
      pendingDelta = '';
      setChatMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId
            ? { ...msg, content: msg.content + delta, thinkingLabel: undefined }
            : msg
        )
      );
    };

    try {
      await streamChatSessionMessage(
        session.access_token,
        currentSessionId,
        text,
        {
          onThinking: (title) => {
            // Every title is kept (the page can expand them after the reply);
            // thinkingLabel is just the latest one, shown until the answer
            // starts. Same de-duplication as the backend's stored copy.
            setChatMessages((prev) =>
              prev.map((msg) => {
                if (msg.id !== assistantMsgId) return msg;
                const list = msg.thinking ?? [];
                // Filler words only keep the live label moving; they are not steps.
                const thinking =
                  isThinkingFiller(title) || list[list.length - 1] === title ? list : [...list, title];
                return { ...msg, thinking, thinkingLabel: msg.content ? undefined : title };
              })
            );
          },
          onToken: (delta) => {
            pendingDelta += delta;
            if (flushTimer === null) flushTimer = setTimeout(flushTokens, 40);
          },
          onDone: (_fullText) => {
            flushTokens();
            const latencyMs = Math.round(performance.now() - startTime);
            setChatMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMsgId ? { ...msg, latencyMs, thinkingLabel: undefined } : msg
              )
            );
            // Refresh billing & session list
            refreshBilling().catch(() => {});
            loadChatSessions().catch(() => {});
          },
          onError: (_err) => {
            // Will be caught by surrounding try/catch
          },
        },
        {
          reasoningEffort: levelForModel(modelName, thinkingLevelsRef.current[modelName]),
          ...(attached.length > 0 ? { images: attached.map(({ data, mime }) => ({ data, mime })) } : {}),
        }
      );
    } catch (err: any) {
      flushTokens(); // keep every token that arrived before the failure
      // The connection dropped (went offline, a flaky network, a suspended
      // tab). That is not a failed reply: it keeps generating on the server
      // and is saved when done. Keep what is on screen and follow it; if the
      // message never arrived, followPendingReply turns that into a Retry.
      if (err instanceof ApiError && err.code === CONNECTION_LOST) {
        following = true;
        void followPendingReply(currentSessionId, sessionRequestRef.current, { text, at: stamp });
        return; // isGenerating stays on until the follow ends
      }
      let errorContent = "Couldn't reach Quancis, please try again.";

      if (err instanceof ApiError) {
        if (err.status === 402 || err.type === 'insufficient_balance') {
          errorContent = 'Your account balance is too low to run this query. Please visit the Account / Billing page to top up or check your credits.';
        } else if (err.status === 409 && err.code !== 'session_busy') {
          setIsSessionUnresumable(true);
          errorContent = 'This conversation was created with an option that is no longer available and can no longer be continued. Please start a new conversation.';
        } else if (err.status === 404) {
          errorContent = "This playground conversation doesn't exist or isn't yours. Please start a new conversation.";
        } else if (err.message) {
          errorContent = err.message;
        }
      } else if (err?.message) {
        errorContent = err.message;
      }

      // Nothing was saved server-side for a failed send, so the user's
      // message stays on screen with a Retry on the error, and a refresh
      // starts from the last good turn.
      setChatMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantMsgId ? { ...msg, error: errorContent, thinkingLabel: undefined } : msg
        )
      );
      // A conversation created just for this send holds nothing if the send
      // failed (the server does not save a failed turn). Take it out of the
      // sidebar now; it stays open here, so Retry reuses it, and it returns to
      // the list with the first saved reply.
      if (createdHere) {
        const emptyId = currentSessionId;
        setChatSessions((prev) => prev.filter((s) => s.id !== emptyId));
      }
    } finally {
      flushTokens();
      if (!following) setIsGenerating(false);
    }
  };

  // Re-sends the user message that preceded a failed reply. The failed pair
  // is removed first, so the retry replaces it instead of stacking under it.
  const retryChatMessage = async (errorMessageId: string) => {
    if (isGenerating) return;
    const errIdx = chatMessages.findIndex((m) => m.id === errorMessageId);
    if (errIdx < 0) return;
    // A failed send is always [user message, failed reply] back to back. Any
    // other shape (e.g. the "please sign in" notice) has nothing to re-send.
    const userIdx = errIdx - 1;
    if (userIdx < 0 || chatMessages[userIdx].role !== 'user') return;
    const retryContent = chatMessages[userIdx].content;
    // Pictures attached in this page still hold their data and go again. A message
    // whose pictures are only known by id (loaded from the server) cannot be retried
    // from here; the page does not offer Retry for it (see canRetry there).
    const retryImages = (chatMessages[userIdx].images ?? []).filter((i) => typeof i.data === 'string' && i.data.length > 0);
    setChatMessages(chatMessages.slice(0, userIdx));
    await sendChatMessage(retryContent, retryImages);
  };

  const loadAdminStats = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setIsAdminDataLoading(true);
    try {
      const stats = await getAdminStatsApi(session.access_token);
      setAdminStats(stats);
    } catch (err) {
      console.warn('Failed to load admin stats:', err);
      throw err;
    } finally {
      setIsAdminDataLoading(false);
    }
  }, []);

  const loadAdminUsers = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) return;

    setIsAdminDataLoading(true);
    try {
      const res = await getAdminUsersApi(session.access_token);
      setAdminUsers(res.users || []);
    } catch (err) {
      console.warn('Failed to load admin users:', err);
      throw err;
    } finally {
      setIsAdminDataLoading(false);
    }
  }, []);

  const creditAdminUser = useCallback(async (userId: string, amountUsd: number): Promise<CreditAdminUserResponse> => {
    const supabase = getSupabase();
    if (!supabase) throw new Error('Supabase client not initialized');
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('You must be signed in');

    try {
      const res = await creditAdminUserApi(session.access_token, userId, amountUsd);
      setAdminUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, credit_balance_usd: res.new_balance_usd } : u))
      );
      return res;
    } catch (err) {
      console.warn('Failed to credit user:', err);
      throw err;
    }
  }, []);

  const suspendAdminUser = useCallback(async (userId: string): Promise<SuspendAdminUserResponse> => {
    const supabase = getSupabase();
    if (!supabase) throw new Error('Supabase client not initialized');
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('You must be signed in');

    try {
      const res = await suspendAdminUserApi(session.access_token, userId);
      setAdminUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, status: res.status } : u))
      );
      return res;
    } catch (err) {
      console.warn('Failed to suspend user:', err);
      throw err;
    }
  }, []);

  const activateAdminUser = useCallback(async (userId: string): Promise<ActivateAdminUserResponse> => {
    const supabase = getSupabase();
    if (!supabase) throw new Error('Supabase client not initialized');
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('You must be signed in');

    try {
      const res = await activateAdminUserApi(session.access_token, userId);
      setAdminUsers((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, status: res.status } : u))
      );
      return res;
    } catch (err) {
      console.warn('Failed to activate user:', err);
      throw err;
    }
  }, []);

  // Billing reconciliation on demand (read-only on the server). Deliberately
  // does not touch any stored state: the result is shown by the caller and is
  // only meaningful at the moment it was run.
  const runAdminReconcile = useCallback(async (): Promise<ReconcileAdminResponse> => {
    const supabase = getSupabase();
    if (!supabase) throw new Error('Supabase client not initialized');
    const { data: { session } } = await supabase.auth.getSession();
    if (!session?.access_token) throw new Error('You must be signed in');

    try {
      return await runAdminReconcileApi(session.access_token);
    } catch (err) {
      console.warn('Failed to run reconcile check:', err);
      throw err;
    }
  }, []);

  return (
    <AppContext.Provider
      value={{
        isLoggedIn,
        authChecked,
        user,
        isStatsLoading,
        loadStats,
        publicConfig,
        billing,
        billingLoading,
        refreshBilling,
        login,
        logout,
        deleteAccount,
        apiKeys,
        isApiKeysLoading,
        loadApiKeys,
        createApiKey,
        updateApiKeyThinkingLevel,
        deleteApiKey,
        requestLogs,
        usageHistory,
        usageByProduct,
        chatMessages,
        isGenerating,
        chatSessions,
        activeSessionId,
        isSessionsLoading,
        isSessionUnresumable,
        isSessionLoading,
        sessionsError,
        sessionLoadError,
        loadChatSessions,
        startNewChatSession,
        selectChatSession,
        renameChatSession,
        deleteChatSession,
        sendChatMessage,
        selectedModel,
        setSelectedModel,
        activeModel,
        thinkingLevel,
        setThinkingLevel,
        retryChatMessage,
        clearChat,
        updateUserProfile,
        signInWithGitHub,
        signInWithGoogle,
        signInWithEmail,
        signUpWithEmail,
        requestPasswordReset,
        resendConfirmationEmail,
        updatePassword,
        changeOwnPassword,
        saveDisplayName,
        updateNotificationPrefs,
        isSupabaseReady: isSupabaseConfigured,
        adminStats,
        adminUsers,
        isAdminDataLoading,
        loadAdminStats,
        loadAdminUsers,
        creditAdminUser,
        suspendAdminUser,
        activateAdminUser,
        runAdminReconcile,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
