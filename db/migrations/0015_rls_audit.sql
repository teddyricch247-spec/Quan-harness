-- 0015_rls_audit.sql
-- Quan Harness — Phase 6.2 (step 20) — lets the isolation suite ask the database what it actually contains.
--
-- WHY. §5 says the RLS suite must run on every pull request that touches a table's schema or policies. A suite that
-- only tests the tables somebody remembered to list fails silently the day a table is added without a test — which is
-- exactly how six tables (deploy_runs, preview_secrets, project_notifications, project_schedules, project_secrets,
-- project_workspaces) went untested after Phase 4. So the suite compares its own table registry with the CATALOG:
-- every table in `public` must be registered, have RLS on and at least one policy; every policy must be scoped by
-- auth.uid(); every foreign key between two user-owned tables must be declared; and no function in `public` may be
-- callable by a signed-in or anonymous caller except the ones deliberately meant to be (this one).
--
-- WHAT IT RETURNS. Names and flags only — table names, policy text, foreign-key columns, function names and who may
-- execute them. No row data of any account, ever. (Table and column names are already public to any caller through
-- PostgREST's own schema document.) It is SECURITY INVOKER on purpose — pg_policies, pg_class, pg_constraint and
-- has_function_privilege() are readable by every role, so it needs no elevated rights (Supabase's security advisor
-- flags a SECURITY DEFINER function that signed-in users can call) — and it is executable by `authenticated` only:
-- the suite calls it as a signed-in test account.
--
-- Purely additive. Roll back with `drop function public.rls_audit();`.

create function public.rls_audit()
returns jsonb
language sql stable security invoker set search_path = pg_catalog, public as $$
    select jsonb_build_object(
        'tables', (
            select coalesce(jsonb_agg(jsonb_build_object('name', c.relname, 'rls', c.relrowsecurity) order by c.relname), '[]'::jsonb)
              from pg_class c join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public' and c.relkind in ('r', 'p')
        ),
        'policies', (
            select coalesce(jsonb_agg(jsonb_build_object(
                       'table', p.tablename, 'name', p.policyname, 'cmd', p.cmd, 'roles', p.roles::text,
                       'using', p.qual, 'check', p.with_check) order by p.tablename, p.policyname), '[]'::jsonb)
              from pg_policies p where p.schemaname = 'public'
        ),
        'foreign_keys', (
            select coalesce(jsonb_agg(jsonb_build_object(
                       'table', k.conrelid::regclass::text, 'column', a.attname, 'references', k.confrelid::regclass::text)
                       order by k.conrelid::regclass::text, a.attname), '[]'::jsonb)
              from pg_constraint k join pg_attribute a on a.attrelid = k.conrelid and a.attnum = any (k.conkey)
             where k.contype = 'f' and k.connamespace = 'public'::regnamespace
        ),
        'functions', (
            select coalesce(jsonb_agg(jsonb_build_object(
                       'name', f.proname, 'returns', pg_get_function_result(f.oid), 'security_definer', f.prosecdef,
                       'authenticated_can_execute', has_function_privilege('authenticated', f.oid, 'execute'),
                       'anon_can_execute', has_function_privilege('anon', f.oid, 'execute')) order by f.proname), '[]'::jsonb)
              from pg_proc f where f.pronamespace = 'public'::regnamespace
        )
    );
$$;

revoke all on function public.rls_audit() from public, anon;
grant execute on function public.rls_audit() to authenticated, service_role;
