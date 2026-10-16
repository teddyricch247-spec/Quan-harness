export interface UserProfile {
  id: string;
  name: string;
  email: string;
  avatar: string;
  tier: 'Developer' | 'Scale' | 'Enterprise';
  role?: 'admin' | 'user';
  creditBalance?: number | null;
  monthlySpend?: number | null;
  createdAt: string;
  // Primary Supabase Auth provider ('email', 'google', 'github', ...) —
  // read from app_metadata.provider, which only the GoTrue admin API can
  // write, never the user themselves. Used to decide whether a password
  // change makes sense for this account at all (OAuth-only accounts have
  // no password on our side to change).
  provider: string;
  // Persisted in Supabase Auth user_metadata (self-editable by the user
  // via supabase.auth.updateUser({ data: {...} })) — not a separate
  // table, since this is per-account preference, not app data.
  lowBalanceAlertEnabled: boolean;
  lowBalanceAlertThresholdUsd: number;
}

export interface ApiKey {
  id: string;
  name: string;
  key: string;
  prefix: string;
  createdAt: string;
  lastUsedAt: string;
  active: boolean;
  // 'sdk' (the request decides), or a level that belongs to one model:
  // 'low' | 'high' | 'max' (Kael Beta) or 'z-low' | 'z-high' (Kael Pro Beta).
  // See lib/thinkingLevels.ts.
  thinkingLevel: string;
}

export interface CompoundStepTrace {
  id: string;
  nodeName: string;
  nodeType: 'router' | 'coder' | 'planner' | 'critic' | 'synthesizer' | 'verifier';
  modelUsed: string;
  cost: number;
  timeMs: number;
  status: 'completed' | 'skipped' | 'active';
  description: string;
  subOutput?: string;
}

// A picture attached to a playground message. A picture the user just attached
// has `src` (a local preview URL) and `data` (its base64, kept only so a failed
// send can be retried). A picture loaded from a saved conversation has an `id`
// and no `src`: the page fetches its bytes on demand (see AttachedImage).
export interface ChatMessageImage {
  id?: string;
  mime: string;
  src?: string;
  data?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  model: string;
  tokenUsage?: {
    inputTokens: number;
    cachedInputTokens: number;
    outputTokens: number;
    totalCost: number;
    savedVsFrontier: number;
  };
  reasoningTraces?: CompoundStepTrace[];
  latencyMs?: number;
  accuracyConfidence?: number;
  // Playground only. `error` is set on an assistant message whose reply
  // failed (any partial `content` is kept above it) so the page can show a
  // real error state with a Retry button instead of error text posing as a
  // reply. `thinkingLabel` is the latest "thinking title" streamed by the
  // backend while no answer text has arrived yet; transient, never persisted.
  error?: string;
  thinkingLabel?: string;
  // Playground only. Everything Kael streamed as "thinking" for this reply, in
  // order (the same short titles the API sends as reasoning_content). Kept
  // after the answer arrives so it can be expanded, and stored by the backend
  // so it survives a reload.
  thinking?: string[];
  // Playground only. Pictures attached to a user message. `imageCount` is for
  // the one case where only the number is known: a message whose reply was still
  // running when the page was reloaded (its pictures are saved with the reply).
  images?: ChatMessageImage[];
  imageCount?: number;
}

export interface UsageDay {
  date: string;
  inputTokens: number;
  cachedTokens: number;
  outputTokens: number;
  totalRequests: number;
  costDollars: number;
  avgLatencyMs: number;
}

export interface ModelBenchmark {
  metric: string;
  quanAI: number;
  gpt4o: number;
  claude35Sonnet: number;
  o1Mini: number;
  unit: string;
  description: string;
}

export interface RequestLog {
  id: string;
  timestamp: string;
  endpoint: string;
  model: string;
  status: number;
  tokens: number;
  cacheHit: boolean;
  latency: number;
  cost: number;
}
