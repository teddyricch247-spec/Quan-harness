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

// Only true infrastructure config lives here now: how to reach the process's own
// Postgres/auth backend, and where the frontend runs (for CORS). Model providers and
// every other API key (GitHub, Vercel, Tavily, ...) used to be registered here from
// env vars — they're now stored, encrypted, in Supabase and managed from the Settings
// page instead, so they can change without a redeploy. See
// backend/src/services/settingsStore.js.
export const config = {
  port: Number(process.env.PORT || 3000),
  frontendOrigin: process.env.FRONTEND_ORIGIN || 'http://localhost:5173',

  supabaseUrl: required('SUPABASE_URL'),
  supabaseAnonKey: required('SUPABASE_ANON_KEY'),
  supabaseServiceRoleKey: required('SUPABASE_SERVICE_ROLE_KEY'),
};

/** Sane default reasoning_effort for a provider: 'high' if it has one, else its
 * first supported level, else null (provider takes no reasoning param at all). */
export function defaultEffortFor(provider) {
  if (!provider.reasoningEfforts?.length) return null;
  return provider.reasoningEfforts.includes('high') ? 'high' : provider.reasoningEfforts[0];
}
