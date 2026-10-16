# backend/supabase

Database migration files and notes for the Supabase project "quan-ai".

**The live database is the source of truth**, not these files. Read it with
the Supabase MCP tools (`list_migrations`, read-only `execute_sql`,
`get_advisors`). Do not assume a file here has been applied without
checking, and do not assume the live database is fully described by these
files.

## State of `migrations/` (as of 2026-10-13)

- Every file in `migrations/` has been applied to the live project (`0010` and `0011` on 2026-10-07; `0012`, `0013` and `0014` on 2026-10-08)
  - `0012_kael_beta_split.sql`, applied as `kael_beta_split`: the one model keyed `"pro"` became two, so every stored `pro`/`quan-pro` value became `kael-beta`, the retired DeepSeek conversations were deleted, and `api_keys.scopes` was reset. A model's key is its public slug and is stored in the `product` and `model` columns.
  - `0013_api_key_thinking_level.sql`, applied as `api_key_thinking_level`: adds `api_keys.thinking_level`. **This file was first written as `0012_api_key_thinking_level.sql` and renumbered to `0013`** because `kael_beta_split` was applied first. If a `0012_api_key_thinking_level.sql` still exists in the repo, it is the old name of this same migration; delete it.
  - `0014_api_key_thinking_level_comment.sql`, applied as `api_key_thinking_level_comment`: comment-only.
- `0015_chat_message_images.sql`, applied 2026-10-12 as `chat_message_images`: creates `chat_message_images` for pictures attached in the Playground (RLS on, no policies, two indexes). The backend also works without the table (pictures are answered but not kept), so deploy order does not matter.
- `0016_trace_session_link_and_retention.sql` and `0017_expire_credits.sql` (written 2026-10-13) are fully applied (2026-10-15), as plain statements (`execute_sql`, and `purge_expired_chat_traces` by hand in the SQL editor), so they are **not in the `list_migrations` history**. Verification queries are at the bottom of each file.
- The files do not match the live migration history one-to-one:
  - Live has `create_usage_logs`, `api_keys_and_user_scoping` and
    `billing_pin_function_search_path`, which have **no file** here.
  - Numbering is inconsistent: two `0007_*` and two `0008_*` files. The two
    `0008` files contain identical SQL; both are applied.
  - `0006_admin_bootstrap.sql` is a one-off data write, not a schema
    migration, and is not in the live migration list.
- Some files still contain stale comments: "not yet applied"
  (`0007_scopes_default_drop_ultra`, `0008_balance_default_sync`; both are
  applied) and "not live-verified" (`0004_billing`).

A cleanup is planned (`../../PLAN.md`, phase C3): save a schema snapshot
from the live database, delete the applied files, and keep `migrations/`
for unapplied changes only. Until that is done, treat this folder as
history.

## Facts worth knowing

- All 8 public tables have RLS enabled with **no policies**. That is
  deliberate: only the backend (service-role key, which bypasses RLS)
  reads or writes them. Adding policies is planned only as explicit
  deny-all rules (`../../PLAN.md`, C1).
- `deduct_balance`, `credit_balance` and (once `0017` is applied) `expire_credits` are the only code paths that
  change `billing_accounts.balance_usd`; each also writes a
  `billing_ledger` row. Executable by the service role only.
- Applying a change: use Supabase's `apply_migration` for schema changes;
  ask the owner first (it is a production write).
