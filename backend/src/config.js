import 'dotenv/config';

function required(name) {
  const value = process.env[name];
  if (!value) {
    // Fail loudly at boot, not on the first request that needs it.
    console.error(`Missing required env var: ${name}. Copy .env.example to .env and fill it in.`);
    process.exit(1);
  }
  return value;
}

function buildProviders() {
  const providers = {};

  // DeepSeek is always registered — it's the harness's original, required provider.
  providers.deepseek = {
    id: 'deepseek',
    label: 'DeepSeek V4 Flash',
    baseUrl: (process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com').replace(/\/+$/, ''),
    apiKey: required('DEEPSEEK_API_KEY'),
    model: process.env.DEEPSEEK_MODEL || 'deepseek-v4-flash',
    // The three reasoning-effort levels DeepSeek's Responses API actually documents
    // for V4 Flash. See README.md "About the thinking switch" for why there's no
    // separate "medium".
    reasoningEfforts: ['low', 'high', 'max'],
  };

  // Optional second provider: any endpoint that speaks the OpenAI Responses API shape
  // — OpenAI itself, Azure OpenAI's Responses API, a self-hosted gateway, a different
  // vendor's compatible endpoint. Entirely optional: leave CUSTOM_BASE_URL/CUSTOM_API_KEY
  // blank and the harness runs exactly as before, DeepSeek-only, with no provider
  // switcher shown in the UI at all.
  if (process.env.CUSTOM_BASE_URL && process.env.CUSTOM_API_KEY) {
    const effortsRaw = (process.env.CUSTOM_REASONING_EFFORTS || '').trim();
    providers.custom = {
      id: 'custom',
      label: process.env.CUSTOM_LABEL || 'Custom',
      baseUrl: process.env.CUSTOM_BASE_URL.replace(/\/+$/, ''),
      apiKey: process.env.CUSTOM_API_KEY,
      model: process.env.CUSTOM_MODEL || 'gpt-5',
      // Comma-separated, e.g. "low,medium,high" — whatever effort strings your
      // provider's Responses API actually accepts for `reasoning.effort`. Leave this
      // blank if the model doesn't take that param at all (e.g. a non-reasoning
      // model): the harness then omits the `reasoning` field entirely for this
      // provider instead of guessing a value it might reject.
      reasoningEfforts: effortsRaw
        ? effortsRaw.split(',').map((s) => s.trim()).filter(Boolean)
        : [],
    };
  }

  return providers;
}

export const config = {
  port: Number(process.env.PORT || 3000),
  frontendOrigin: process.env.FRONTEND_ORIGIN || 'http://localhost:5173',

  supabaseUrl: required('SUPABASE_URL'),
  supabaseAnonKey: required('SUPABASE_ANON_KEY'),
  supabaseServiceRoleKey: required('SUPABASE_SERVICE_ROLE_KEY'),

  // Every model provider the harness can call, keyed by the id stored in
  // sessions.provider. Always has 'deepseek'; 'custom' only exists if configured.
  // See backend/src/services/responsesApiClient.js for the client that uses this,
  // and GET /api/meta for how the frontend discovers what's available.
  providers: buildProviders(),

  githubToken: required('GITHUB_TOKEN'),
  vercelToken: required('VERCEL_TOKEN'),
  vercelTeamId: process.env.VERCEL_TEAM_ID || null,

  tavilyApiKey: required('TAVILY_API_KEY'),
};

export function getProvider(id) {
  return config.providers[id] || null;
}

/** Sane default reasoning_effort for a provider: 'high' if it has one, else its
 * first supported level, else null (provider takes no reasoning param at all). */
export function defaultEffortFor(provider) {
  if (!provider.reasoningEfforts.length) return null;
  return provider.reasoningEfforts.includes('high') ? 'high' : provider.reasoningEfforts[0];
}
