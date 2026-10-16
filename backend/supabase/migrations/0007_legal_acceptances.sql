-- Records every time a user accepts the Terms of Service or Privacy
-- Policy — added 2026-08-31 because until now the signup checkbox
-- (LoginPage.tsx's `termsAccepted` state) was purely client-side UI: it
-- blocked the submit button but the fact that someone checked it was
-- never sent to the backend, let alone stored anywhere. There was no
-- durable record of consent at all.
--
-- Append-only by design, one row per acceptance EVENT rather than a
-- single mutable "accepted_at" column on the user: if these placeholder
-- Terms/Privacy pages are ever replaced with real ones (or updated
-- later), a fresh acceptance can be recorded as a new row without
-- destroying the history of what was accepted when. `version` is a
-- simple date string matching the "Last updated" date shown on the page
-- at the time of acceptance (see app/config.py's TERMS_VERSION /
-- PRIVACY_VERSION) — bump those constants whenever the page content
-- changes materially, and prompt existing users to re-accept if that
-- ever matters legally.
create table if not exists public.legal_acceptances (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  document text not null check (document in ('terms', 'privacy')),
  version text not null,
  -- How the acceptance happened. 'signup_form' = the email/password
  -- signup checkbox. OAuth (GitHub, Google) doesn't record anything
  -- here yet — those buttons don't currently show the consent
  -- checkbox at all, so there's nothing truthful to log for them.
  method text not null default 'signup_form',
  accepted_at timestamptz not null default now(),
  -- Best-effort, from the request (see rate_limit.client_ip) — not a
  -- guaranteed-accurate value (proxies, shared NAT, etc.), kept anyway
  -- since it's standard practice for this kind of audit record.
  ip_address text,
  user_agent text
);

create index if not exists legal_acceptances_user_id_idx
  on public.legal_acceptances (user_id);

alter table public.legal_acceptances enable row level security;
-- Zero policies, same closed-by-default pattern as api_keys /
-- billing_ledger / usage_logs: only this backend, holding the
-- service_role key, can read or write it. Nothing about consent
-- records should be client-writable — the whole point is that the
-- server, not the browser, is the source of truth for "did this user
-- actually accept."
