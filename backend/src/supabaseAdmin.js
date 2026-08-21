import { createClient } from '@supabase/supabase-js';
import { config } from './config.js';

// Service-role key: full DB access, no RLS. Never expose this client or its key to
// the browser — it only ever lives here, in the backend process.
export const supabaseAdmin = createClient(config.supabaseUrl, config.supabaseServiceRoleKey, {
  auth: { autoRefreshToken: false, persistSession: false },
});

// A second client using the anon key, used ONLY to verify user access tokens sent up
// from the frontend (supabase.auth.getUser(token)). This does not bypass anything —
// it just decodes/validates the JWT against Supabase Auth.
export const supabaseAuthClient = createClient(config.supabaseUrl, config.supabaseAnonKey, {
  auth: { autoRefreshToken: false, persistSession: false },
});
