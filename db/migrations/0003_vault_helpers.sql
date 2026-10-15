-- 0003_vault_helpers.sql
-- Quan Harness — Phase 1 — §13 of the spec: every credential/secret lives in
-- Supabase Vault, never in a plaintext column.
--
-- Vault itself only exposes vault.create_secret()/vault.update_secret() as SQL
-- functions, plus a vault.decrypted_secrets VIEW for reads — none of that is
-- reachable over PostgREST (the supabase-py client's normal .table()/.rpc() calls)
-- unless it's wrapped in a SECURITY DEFINER function that's explicitly granted to
-- the role the backend authenticates as (service_role). These three functions are
-- that wrapper. The backend (backend/app/services/vault.py) calls them via
-- supabase.rpc(...) — it never talks to the vault schema directly.
--
-- SECURITY DEFINER means these run with the privileges of the function's owner
-- (normally `postgres`), not the caller — which is exactly what lets service_role
-- reach into `vault` without being granted broad access to the schema itself.

create or replace function qh_vault_create_secret(p_secret text, p_name text, p_description text default '')
returns uuid
language plpgsql
security definer
set search_path = vault, public
as $$
declare
    v_id uuid;
begin
    v_id := vault.create_secret(p_secret, p_name, p_description);
    return v_id;
end;
$$;

create or replace function qh_vault_read_secret(p_id uuid)
returns text
language plpgsql
security definer
set search_path = vault, public
as $$
declare
    v_secret text;
begin
    select decrypted_secret into v_secret
    from vault.decrypted_secrets
    where id = p_id;
    return v_secret;
end;
$$;

create or replace function qh_vault_update_secret(p_id uuid, p_secret text)
returns void
language plpgsql
security definer
set search_path = vault, public
as $$
begin
    perform vault.update_secret(p_id, p_secret);
end;
$$;

create or replace function qh_vault_delete_secret(p_id uuid)
returns void
language plpgsql
security definer
set search_path = vault, public
as $$
begin
    delete from vault.secrets where id = p_id;
end;
$$;

-- Lock these down to service_role only — this is the whole point of the wrapper.
-- PUBLIC/anon/authenticated must never be able to call these directly, since the
-- backend is the only thing that should ever resolve a raw secret value.
revoke all on function qh_vault_create_secret(text, text, text) from public, anon, authenticated;
revoke all on function qh_vault_read_secret(uuid) from public, anon, authenticated;
revoke all on function qh_vault_update_secret(uuid, text) from public, anon, authenticated;
revoke all on function qh_vault_delete_secret(uuid) from public, anon, authenticated;

grant execute on function qh_vault_create_secret(text, text, text) to service_role;
grant execute on function qh_vault_read_secret(uuid) to service_role;
grant execute on function qh_vault_update_secret(uuid, text) to service_role;
grant execute on function qh_vault_delete_secret(uuid) to service_role;
