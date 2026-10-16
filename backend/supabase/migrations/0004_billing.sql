-- Adds account balances + a billing ledger for Quan Pro — the only
-- product that exists at all as of 2026-08-16 (see app/config.py's
-- BILLED_PRODUCTS and app/billing.py; Flash and Ultra were removed
-- entirely, not just excluded from billing — see models/__init__.py).
--
-- Historical note, current as of the date above only: Ultra was
-- reintroduced and both it and Pro were renamed to "Aura Beta"/"Kael
-- Beta" and went live/billed together on 2026-08-19 — this table's
-- schema (untyped `product text` column) needed no change for that, only
-- app/config.py and each product's own models/*/config.py did. See
-- app/billing.py's module docstring for the current state.
--
-- Renumbered from this repo's original 0002_billing.sql to 0004 — two
-- other migrations (chat_debug_traces, chat_sessions_and_messages) were
-- applied to the live project between 0001 and this one, on a separate
-- track this migration didn't originally account for.
--
-- Confirmed already applied directly to the live project (queried
-- information_schema.tables/routines on 2026-08-16: billing_accounts,
-- billing_ledger, deduct_balance, and credit_balance all exist) — despite
-- what an earlier version of this comment claimed. Nothing to run
-- manually; this file exists so the schema is versioned and reproducible
-- on a fresh project if you ever need one.

create table if not exists public.billing_accounts (
  user_id uuid primary key references auth.users(id) on delete cascade,
  -- 5 decimal places = accurate to 1/1000th of a cent. Worth it here
  -- because per-token pricing is already sub-cent (e.g. $0.14 / 1M input
  -- tokens = $0.00000014/token) — 2 decimal places would round most
  -- individual requests to $0.00 and silently never charge anyone.
  -- New accounts start at $0.00000 as of migration 0008 — see
  -- DEFAULT_STARTING_BALANCE in app/billing.py, kept in sync with this
  -- column default (if you change one, change the other, and add a new
  -- migration for it rather than editing this historical one).
  -- (This default was 5.00000 from when this table was first created
  -- until 0008_balance_default_sync.sql corrected it on 2026-09-15 — an
  -- earlier free-signup-credit decision that DEFAULT_STARTING_BALANCE's
  -- own history had already moved on from without this column following;
  -- see that migration's comment for the full drift.)
  balance_usd numeric(14, 5) not null default 5.00000,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.billing_accounts enable row level security;
-- Zero policies, intentionally — same closed-by-default pattern as
-- api_keys / usage_logs. Only this backend, holding the service_role
-- key, can read or write it. The frontend never talks to Supabase
-- directly for billing data; it goes through /api/billing.

-- Deliberately NO `check (balance_usd >= 0)` constraint. The design is a
-- pre-call gate (billing.check_balance_or_raise — blocks a request before
-- it starts if balance <= 0) plus a post-call deduction based on that
-- request's *actual* usage, which is only known once it's done. The one
-- request that crosses from positive to zero-or-below is allowed to
-- finish and settle the account slightly negative; the *next* one is what
-- gets blocked. A CHECK constraint here would make that settling UPDATE
-- fail instead, which breaks the intended behavior — don't add one.
create table if not exists public.billing_ledger (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  product text,                 -- e.g. 'pro'; null for deposits/adjustments (not tied to a product)
  kind text not null check (kind in ('usage', 'deposit', 'adjustment')),
  amount_usd numeric(14, 5) not null,        -- negative for charges, positive for deposits/credits
  balance_after_usd numeric(14, 5) not null, -- snapshot, so history reads correctly even if disputed/edited later
  billed_prompt_tokens integer,      -- first-call input tokens billed (null for non-'usage' rows)
  billed_cached_tokens integer,      -- subset of the above that were a cache hit — see billing.py
  billed_completion_tokens integer,  -- last-call output tokens billed
  -- Whether time-of-day peak pricing applied to this charge. Retired
  -- 2026-08-19 — pricing is flat now (see app/billing.py's "Pricing is
  -- flat" docstring section), so every new row is always false. Column
  -- kept rather than dropped since this migration is already applied to
  -- the live project; a future migration would formally drop it if
  -- peak pricing is confirmed gone for good. Always false for non-'usage'
  -- rows (deposits/adjustments) too; not meaningful there.
  is_peak boolean not null default false,
  description text,
  created_at timestamptz not null default now()
);

-- Optimizes the one query this table actually serves: "this user's most
-- recent entries" (app/billing.py's fetch_billing_summary).
create index if not exists billing_ledger_user_id_created_at_idx
  on public.billing_ledger (user_id, created_at desc);

alter table public.billing_ledger enable row level security;
-- Same closed-by-default pattern — service_role only.

-- ============================================================
-- Atomic balance mutation. Both are a single UPDATE ... RETURNING plus one
-- INSERT, inside one implicit transaction (a plpgsql function body is
-- transactional by default) — so two concurrent requests against the same
-- account can never both read a stale balance and both think they can
-- afford their own charge (the lost-update race a Python-side
-- read-balance-then-write-balance would be exposed to). This is the one
-- place that race actually matters; the pre-call balance *check* in
-- billing.py is a plain read and doesn't need this.
-- ============================================================

create or replace function public.deduct_balance(
  p_user_id uuid,
  p_amount numeric,
  p_product text,
  p_billed_prompt_tokens integer,
  p_billed_cached_tokens integer,
  p_billed_completion_tokens integer,
  p_description text,
  p_is_peak boolean default false
)
returns numeric
language plpgsql
-- Every table reference in the body below is already schema-qualified
-- (public.billing_accounts, public.billing_ledger), so pinning this to
-- empty is a pure hardening change — closes the Postgres linter's
-- "Function Search Path Mutable" warning with no behavior difference.
set search_path = ''
as $$
declare
  v_new_balance numeric(14, 5);
begin
  update public.billing_accounts
    set balance_usd = balance_usd - p_amount,
        updated_at = now()
    where user_id = p_user_id
    returning balance_usd into v_new_balance;

  if v_new_balance is null then
    raise exception 'billing_accounts row not found for user %', p_user_id;
  end if;

  insert into public.billing_ledger
    (user_id, product, kind, amount_usd, balance_after_usd,
     billed_prompt_tokens, billed_cached_tokens, billed_completion_tokens, is_peak, description)
  values
    (p_user_id, p_product, 'usage', -p_amount, v_new_balance,
     p_billed_prompt_tokens, p_billed_cached_tokens, p_billed_completion_tokens, p_is_peak, p_description);

  return v_new_balance;
end;
$$;

-- Not called from any HTTP route yet — there's no real payment processor
-- behind the dashboard's (deliberately disabled) "Pay" button yet. This
-- exists so that wiring one up later (e.g. a Stripe webhook handler) is
-- "call this function," not "design the ledger from scratch." Don't
-- expose this over an authenticated-user-facing endpoint without a real
-- payment verification step in front of it — a logged-in user calling
-- this directly would just be able to mint themselves free balance.
create or replace function public.credit_balance(
  p_user_id uuid,
  p_amount numeric,
  p_description text
)
returns numeric
language plpgsql
set search_path = ''
as $$
declare
  v_new_balance numeric(14, 5);
begin
  update public.billing_accounts
    set balance_usd = balance_usd + p_amount,
        updated_at = now()
    where user_id = p_user_id
    returning balance_usd into v_new_balance;

  if v_new_balance is null then
    raise exception 'billing_accounts row not found for user %', p_user_id;
  end if;

  insert into public.billing_ledger (user_id, product, kind, amount_usd, balance_after_usd, description)
  values (p_user_id, null, 'deposit', p_amount, v_new_balance, p_description);

  return v_new_balance;
end;
$$;

-- Not live-verified yet: this hasn't been run against a real Supabase
-- project, and the PostgREST RPC numeric-parameter path (app/billing.py
-- sends p_amount as a JSON number) hasn't been smoke-tested end-to-end.
-- Same spirit as the top-level README's note on the critic feature not
-- being live-verified against DeepSeek yet — do one real test call before
-- trusting this in production.
