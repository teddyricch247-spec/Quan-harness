// Every number and address the docs quote lives here, so a price or limit
// change is one edit in one file (plus the hardcoded-pricing list in
// frontend/README.md, which this file is now part of).
//
// Sources of truth in the backend:
//   models, tiers, price  backend/app/models/kael/config.py  KAEL_BETA, KAEL_PRO_BETA
//                         (customer_price_per_million, reasoning_tiers, default_reasoning_tier)
//   context/output        backend/app/models/kael/config.py  context_window, max_output
//   rate limits           backend/app/rate_limit.py          PRODUCT_RATE_*, PRODUCT_MAX_CONCURRENT_PER_USER
//   time limit            backend/app/two_pass_pipeline.py   GENERATION_HARD_CEILING_SECONDS
//
// If a number here and the backend disagree, the backend wins: fix this file.
// lib/api.ts MODELS lists the same two models for the Playground; keep the two
// in step (id, name, thinking levels, default level).

// Kael Beta: the general model. Three levels.
export const BETA = {
  id: 'kael-beta',
  name: 'Kael Beta',
  price: { input: 3.0, cachedInput: 0.6, output: 10.0 },
  thinkingLevels: ['low', 'high', 'max'],
  defaultLevel: 'low',
} as const;

// Kael Pro Beta: the more thorough model. Two z levels. Priced higher per token
// (owner decision 2026-10-08: $8 in / $25 out; cached input is 20% of input, the
// same rule as Kael Beta). Customer-facing text must say what it is for, never
// how it works (see frontend/README.md, "never describe how Kael produces an
// answer").
export const PRO_BETA = {
  id: 'kael-pro-beta',
  name: 'Kael Pro Beta',
  price: { input: 8.0, cachedInput: 1.6, output: 25.0 },
  thinkingLevels: ['z-low', 'z-high'],
  defaultLevel: 'z-low',
} as const;

export const MODEL_FACTS = [BETA, PRO_BETA] as const;

// What is the same for both models.
export const KAEL = {
  keyPrefix: 'sk-quan-',

  // OpenAI SDKs append /chat/completions or /responses to this.
  openaiBase: 'https://api.quancis.space/v1',
  // Anthropic SDKs append /v1/messages themselves, so their base has no /v1.
  anthropicBase: 'https://api.quancis.space',

  // Every thinking level of both models, in the order the dashboard lists them.
  thinkingLevels: [...BETA.thinkingLevels, ...PRO_BETA.thinkingLevels],

  contextWindow: '1M tokens',
  maxOutput: '128,000 tokens',

  // Per account, counted across both models together.
  requestsPerMinute: 150,
  concurrentRequests: 30,
  ipRequestsPerMinute: 300,
  // NOT a per-request limit. The backend's 480 s hard ceiling
  // (GENERATION_HARD_CEILING_SECONDS in backend/app/two_pass_pipeline.py)
  // applies to each stage of a request, and a request has several stages
  // (up to three on Kael Pro Beta), so one request can run for about 24
  // minutes. What the docs tell clients is the timeout to set on their side:
  // comfortably above that. Never publish 8 minutes as the time a request gets.
  clientTimeoutMinutes: 30,

  playgroundMessageChars: '100,000',
  playgroundHistoryMessages: 200,
  playgroundHistoryChars: '400,000',
} as const;

// Only what is meant to be public: two inboxes, the trading name, and the
// region (which the Terms and Privacy Policy already state). No personal name
// and no street address.
export const CONTACT = {
  support: 'support@quancis.space',
  business: 'response@quancis.space',
  company: 'Quancis',
  region: 'Limpopo, South Africa',
} as const;

export const usd = (n: number): string => `$${n.toFixed(2)}`;

// ["low", "high", "max"] -> "low, high and max", for sentences.
export const listWords = (items: readonly string[]): string =>
  items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
