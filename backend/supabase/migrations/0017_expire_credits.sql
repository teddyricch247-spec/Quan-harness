-- Credits expire 12 months after they are added (owner decision, 2026-10-13;
-- see the Terms of Service, "Credits and Billing"). The decision of WHICH
-- credits have expired is made in Python (app/credit_expiry.py: a first-in
-- first-out replay of the account's ledger, unit-tested). This function only
-- applies the result, atomically, the same way deduct_balance and
-- credit_balance apply a charge or a deposit:
--
--   * it locks the account row (a concurrent charge waits for it);
--   * it refuses to write if the account's ledger no longer has the number of
--     rows the caller computed from (p_ledger_rows), i.e. a charge or deposit
--     landed after the caller read the ledger. It returns NULL in that case and
--     the next daily run recomputes. This stops a stale calculation from
--     removing credits that a request has just used;
--   * it lowers balance_usd and writes one ledger row of kind 'adjustment'
--     (negative amount, description starting "Expired credits") in the same
--     transaction, so the reconcile check still balances.
--
-- Executable by the service role only. Do not expose it over an
-- authenticated-user endpoint: it removes money from a balance.
--
-- Safe to run more than once. Nothing calls it until the backend that contains
-- app/credit_expiry.py is deployed.

begin;

create or replace function public.expire_credits(
  p_user_id uuid,
  p_amount numeric,
  p_description text,
  p_ledger_rows integer
)
returns numeric
language plpgsql
set search_path = ''
as $$
declare
  v_new_balance numeric(14, 5);
  v_rows integer;
begin
  if p_amount is null or p_amount <= 0 then
    raise exception 'expire_credits: amount must be positive';
  end if;

  -- Lock the account row. deduct_balance / credit_balance update this same
  -- row, so a charge that has not committed yet makes us wait, and one that
  -- starts after we hold the lock waits for us.
  perform 1 from public.billing_accounts where user_id = p_user_id for update;
  if not found then
    raise exception 'billing_accounts row not found for user %', p_user_id;
  end if;

  select count(*) into v_rows from public.billing_ledger where user_id = p_user_id;
  if v_rows <> p_ledger_rows then
    return null;  -- the ledger changed since the caller read it; skip, retry next run
  end if;

  update public.billing_accounts
    set balance_usd = balance_usd - p_amount,
        updated_at = now()
    where user_id = p_user_id
    returning balance_usd into v_new_balance;

  insert into public.billing_ledger (user_id, product, kind, amount_usd, balance_after_usd, description)
  values (p_user_id, null, 'adjustment', -p_amount, v_new_balance, p_description);

  return v_new_balance;
end;
$$;

revoke all on function public.expire_credits(uuid, numeric, text, integer) from public, anon, authenticated;
grant execute on function public.expire_credits(uuid, numeric, text, integer) to service_role;

commit;

-- Verify afterwards:
--   select has_function_privilege('anon', 'public.expire_credits(uuid, numeric, text, integer)', 'execute');          -- false
--   select has_function_privilege('authenticated', 'public.expire_credits(uuid, numeric, text, integer)', 'execute'); -- false
--   select has_function_privilege('service_role', 'public.expire_credits(uuid, numeric, text, integer)', 'execute');  -- true
