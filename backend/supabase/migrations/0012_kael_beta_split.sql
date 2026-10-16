-- 2026-10-08: the single model keyed "pro" became two models, "kael-beta" and
-- "kael-pro-beta" (see backend/app/models/kael/config.py). A model's key is now
-- its public slug, so every legacy name is removed or renamed here and the code
-- no longer knows any of them.
--
-- Owner decision (2026-10-08): everything in this database is test data, so
-- nothing is preserved for its own sake. The rows below are renamed anyway where
-- that is simply the right value, and deleted where the thing they describe no
-- longer exists. Not reversible by design.
--
-- What each statement does:
--   1. Deletes playground conversations that were created on the retired
--      direct-DeepSeek option ('deepseek-v4-flash'), which the app no longer
--      offers. Their messages go with them (chat_messages.session_id is
--      ON DELETE CASCADE). They could not be resumed, only read.
--   2. Renames 'pro' and the retired alias 'quan-pro' in chat_sessions.model to
--      'kael-beta'. Those were all Kael Beta conversations.
--   3. Renames product 'pro' to 'kael-beta' in usage_logs, billing_ledger and
--      chat_debug_traces. Amounts, tokens and balances are untouched, so
--      billing reconciliation is unaffected.
--   4. api_keys.scopes held {flash, pro, ultra} / {pro}: names of products that
--      no longer exist (nothing reads this column; see app/api_keys.py). Every
--      key now lists the two current models, and so does the column default.
--   5. Updates the one column comment that named the old keys.
--
-- Safe to run more than once: after the first run every WHERE matches nothing.
-- (No explicit begin/commit: Supabase's apply_migration wraps the file in one.)

delete from public.chat_sessions
 where model = 'deepseek-v4-flash';

update public.chat_sessions
   set model = 'kael-beta'
 where model in ('pro', 'quan-pro');

update public.usage_logs
   set product = 'kael-beta'
 where product = 'pro';

update public.billing_ledger
   set product = 'kael-beta'
 where product = 'pro';

update public.chat_debug_traces
   set product = 'kael-beta'
 where product = 'pro';

update public.api_keys
   set scopes = array['kael-beta', 'kael-pro-beta']::text[]
 where scopes is distinct from array['kael-beta', 'kael-pro-beta']::text[];

alter table public.api_keys
  alter column scopes set default array['kael-beta', 'kael-pro-beta']::text[];

comment on column public.chat_sessions.model is
  'The model a playground conversation is locked to: its public slug, which is also its key in config.PRODUCTS (''kael-beta'' or ''kael-pro-beta''). Any other value is not resumable. See app/main.py, _resolve_session_product.';

-- Verify afterwards (each should return 0 rows):
--   select product, count(*) from public.usage_logs where product is not null and product not in ('kael-beta','kael-pro-beta') group by product;
--   select product, count(*) from public.billing_ledger where product is not null and product not in ('kael-beta','kael-pro-beta') group by product;
--   select product, count(*) from public.chat_debug_traces where product is not null and product not in ('kael-beta','kael-pro-beta') group by product;
--   select model, count(*) from public.chat_sessions where model not in ('kael-beta','kael-pro-beta') group by model;
