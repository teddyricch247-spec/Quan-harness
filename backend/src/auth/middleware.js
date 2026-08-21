import { supabaseAuthClient } from '../supabaseAdmin.js';

// This is a single-user app: there's exactly one Supabase user (created manually in
// the dashboard, signups disabled). We don't check *which* user — just that the
// bearer token is a valid, current Supabase session token. If you ever add more
// users, this is the place to also check req.user.id against an allow-list.
export async function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const token = header.startsWith('Bearer ') ? header.slice('Bearer '.length) : null;

  if (!token) {
    return res.status(401).json({ error: 'Missing Authorization: Bearer <token> header.' });
  }

  const { data, error } = await supabaseAuthClient.auth.getUser(token);
  if (error || !data?.user) {
    return res.status(401).json({ error: 'Invalid or expired token.' });
  }

  req.user = data.user;
  next();
}
