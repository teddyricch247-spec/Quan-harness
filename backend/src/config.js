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

export const config = {
  port: Number(process.env.PORT || 3000),
  frontendOrigin: process.env.FRONTEND_ORIGIN || 'http://localhost:5173',

  supabaseUrl: required('SUPABASE_URL'),
  supabaseAnonKey: required('SUPABASE_ANON_KEY'),
  supabaseServiceRoleKey: required('SUPABASE_SERVICE_ROLE_KEY'),

  deepseekApiKey: required('DEEPSEEK_API_KEY'),
  deepseekBaseUrl: (process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com').replace(/\/+$/, ''),
  deepseekModel: process.env.DEEPSEEK_MODEL || 'deepseek-v4-flash',

  githubToken: required('GITHUB_TOKEN'),
  vercelToken: required('VERCEL_TOKEN'),
  vercelTeamId: process.env.VERCEL_TEAM_ID || null,

  tavilyApiKey: required('TAVILY_API_KEY'),
};

// The three reasoning-effort levels DeepSeek's Responses API actually documents for
// V4 Flash. See README.md "About the thinking switch" for why there's no "medium".
export const REASONING_EFFORTS = ['low', 'high', 'max'];
