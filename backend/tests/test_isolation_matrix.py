"""
Phase 6.2 (§5, Implementation Order step 20) — the isolation verification, raw-database path.

    "Two real accounts, A and B. There must be NO PATH — UI, direct API call, or raw RLS-scoped query — by which
     one can see or affect anything belonging to the other."

This file is the raw-RLS-scoped-query path: every query goes through PostgREST as the `authenticated` role with
account B's OWN token (the anon key plus a real sign-in — what any browser holds), against rows account A really
created. test_isolation_api.py is the direct-API-call path (the backend's own HTTP surface); there is no UI to
test yet, and the data it would show is exactly what these two files prove can't cross.

What is generated from the registry (isolation_registry.py), for EVERY user-owned table:
  read      B's lookup of A's row by key finds nothing, and B's unfiltered select never contains it
  update    B updating A's row changes nothing (zero rows, A's value unchanged)
  delete    B deleting A's row deletes nothing
  insert    B inserting a row INTO A's scope (A's project/session/connector/account) is refused
  move      B re-pointing B's OWN row at A's scope is refused
  cross-references   B writing a row of its own that POINTS AT one of A's rows is refused — for every foreign key
                     the registry declares (the paths an owner policy that only checks the row's own scope misses)
  same-account, different project   references can't cross project boundaries even for one account
  anonymous callers  see nothing and write nothing
and from the database's own catalog (migration 0015's rls_audit), the guards that make the above impossible to
outgrow: every table is registered, has RLS and a policy, every policy is keyed on auth.uid(), every foreign key
between owned tables is declared, and no function in `public` is callable by a client except the audit itself.

Reading a failure: "the write SUCCEEDED" means the database accepted something it must not — fix the policy, not
the test. "refused for the wrong reason" means the attack never reached the policy (a bad payload, a constraint),
so the test proves nothing until the factory in isolation_registry.py is fixed.

Needs the env vars in conftest.py and migrations 0013-0015 applied to the project the tests run against. Not run
offline: only test_registry_is_internally_consistent and the registry import work without a database.
"""
import pytest

from tests.isolation_registry import (
    BY_NAME,
    CLIENT_CALLABLE_FUNCTIONS,
    EXEMPT_TABLES,
    TABLES,
    VAULT_REF_COLUMNS,
    World,
)

try:  # supabase-py's PostgREST error
    from postgrest.exceptions import APIError
except Exception:  # noqa: BLE001 — keeps the offline registry test importable without the package
    APIError = Exception  # type: ignore[assignment,misc]

RLS_REFUSAL = ("42501",)                    # new row violates row-level security policy / permission denied
REFERENCE_REFUSAL = ("42501", "P0001")      # …or an ownership trigger (the `projects` credential references)

ids = lambda t: t.name  # noqa: E731
CROSS_REFS = [(t, column, target) for t in TABLES for column, target in t.cross_refs.items()]


# ---------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------


def code_of(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if not code and getattr(exc, "args", None) and isinstance(exc.args[0], dict):
        code = exc.args[0].get("code")
    return str(code or "")


def assert_refused(call, *, what: str, allowed=RLS_REFUSAL):
    """`call()` must raise a database refusal whose code is in `allowed`. Succeeding is the failure this suite
    exists to catch; any other error means the attack was malformed and proved nothing."""
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001
        code = code_of(exc)
        assert code in allowed, f"{what}: refused for the wrong reason ({code or type(exc).__name__}): {exc}"
        return
    pytest.fail(f"{what}: the write SUCCEEDED — account B wrote through RLS. Returned: {getattr(result, 'data', result)}")


def by_pk(query, table, row):
    for column in table.pk:
        query = query.eq(column, row[column])
    return query


def fetch(client, table, row) -> list[dict]:
    return by_pk(client.table(table.name).select("*"), table, row).execute().data


def pk_of(table, row) -> tuple:
    return tuple(row[c] for c in table.pk)


# ---------------------------------------------------------------------------------------------------------
# the registry itself (runs offline)
# ---------------------------------------------------------------------------------------------------------


def test_registry_is_internally_consistent():
    class FakeAuth:
        def get_user(self):
            return type("R", (), {"user": type("U", (), {"id": "00000000-0000-0000-0000-000000000001"})()})()

    world = World(type("C", (), {"auth": FakeAuth()})(), "T")
    names = [t.name for t in TABLES]
    assert len(set(names)) == len(names)
    seen: set[str] = set()
    for table in TABLES:
        # World.build() creates one row per table in this order, so a table's SCOPE parent must come first. Cross-
        # reference targets need only exist (they are filled in by the attacks, never by the factories — which is
        # also why sessions.schedule_id and project_schedules.last_session_id can point at each other).
        for column, target in table.cross_refs.items():
            assert target in BY_NAME, f"{table.name}.{column} points at unregistered {target}"
        scope_parent = {"project_id": "projects", "session_id": "sessions", "mcp_server_id": "mcp_servers"}.get(table.scope)
        assert scope_parent is None or scope_parent in seen, f"{table.name}: {scope_parent} must be registered BEFORE it"
        assert table.scope in ("user_id", "project_id", "session_id", "mcp_server_id"), table.name
        # every factory yields a payload carrying its scope column, and honours an override
        world.rows.update({n: {"id": f"id-of-{n}", **{c: f"{n}-{c}" for c in BY_NAME[n].pk}} for n in seen})
        payload = table.make(world, {})
        assert table.scope in payload, table.name
        marker = "OVERRIDDEN"
        assert table.make(world, {table.scope: marker})[table.scope] == marker, table.name
        for column in table.cross_refs:
            assert table.make(world, {column: marker})[column] == marker, f"{table.name}.{column}"
        assert table.mutate, table.name
        seen.add(table.name)
    assert set(VAULT_REF_COLUMNS) <= set(names)
    assert not (set(names) & EXEMPT_TABLES)


# ---------------------------------------------------------------------------------------------------------
# read / update / delete
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_b_cannot_read_a_row(table, world_a, client_a, client_b):
    row = world_a.rows[table.name]
    assert fetch(client_a, table, row), f"fixture problem: A cannot see its own {table.name} row"  # the control: the row is really there
    assert fetch(client_b, table, row) == []
    visible = client_b.table(table.name).select(",".join(table.pk)).execute().data
    assert pk_of(table, row) not in {pk_of(table, r) for r in visible}, f"{table.name}: B's unfiltered select contains A's row"


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_b_cannot_update_a_row(table, world_a, client_a, client_b):
    row = world_a.rows[table.name]
    result = by_pk(client_b.table(table.name).update(table.mutate), table, row).execute()
    assert result.data == [], f"{table.name}: B's update of A's row matched {len(result.data)} row(s)"
    after = fetch(client_a, table, row)[0]
    for column in table.mutate:
        assert after[column] == row[column], f"{table.name}.{column} was changed by B"


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_b_cannot_delete_a_row(table, world_a, client_a, client_b):
    row = world_a.rows[table.name]
    result = by_pk(client_b.table(table.name).delete(), table, row).execute()
    assert result.data == [], f"{table.name}: B's delete matched {len(result.data)} row(s)"
    assert fetch(client_a, table, row), f"{table.name}: A's row is gone after B's delete"


# ---------------------------------------------------------------------------------------------------------
# writing INTO A's scope, and moving B's own row into it
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_b_cannot_insert_a_row_into_a_scope(table, world_a, world_b, client_b):
    payload = table.make(world_b, {table.scope: world_a.scope_value(table.scope)})
    assert_refused(lambda: client_b.table(table.name).insert(payload).execute(), what=f"{table.name}: insert into A's {table.scope}")


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_b_cannot_move_its_own_row_into_a_scope(table, world_a, world_b, client_b):
    row = world_b.rows[table.name]
    change = {table.scope: world_a.scope_value(table.scope)}
    assert_refused(
        lambda: by_pk(client_b.table(table.name).update(change), table, row).execute(),
        what=f"{table.name}: re-pointing B's own row's {table.scope} at A's",
    )
    assert fetch(client_b, table, row), f"{table.name}: B's own row vanished"


# ---------------------------------------------------------------------------------------------------------
# cross-references: a row of B's own that POINTS AT something of A's
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table,column,target", CROSS_REFS, ids=[f"{t.name}.{c}" for t, c, _ in CROSS_REFS])
def test_b_cannot_point_a_new_row_at_a_row_of_a(table, column, target, world_a, world_b, client_b):
    payload = table.make(world_b, {column: world_a.ref(target)})
    assert_refused(
        lambda: client_b.table(table.name).insert(payload).execute(),
        what=f"{table.name}.{column} -> A's {target}",
        allowed=REFERENCE_REFUSAL,
    )


@pytest.mark.parametrize("table,column,target", CROSS_REFS, ids=[f"{t.name}.{c}" for t, c, _ in CROSS_REFS])
def test_b_cannot_re_point_its_own_row_at_a_row_of_a(table, column, target, world_a, world_b, client_b):
    row = world_b.rows[table.name]
    change = {column: world_a.ref(target)}
    assert_refused(
        lambda: by_pk(client_b.table(table.name).update(change), table, row).execute(),
        what=f"{table.name}.{column}: updating B's own row to point at A's {target}",
        allowed=REFERENCE_REFUSAL,
    )


# The same idea inside ONE account: a reference must stay inside its project, so deleting one project can never
# reach into another's rows.
SAME_PROJECT = [
    ("sessions", "schedule_id", "project_schedules"),
    ("checkpoints", "session_id", "sessions"),
    ("project_memory_log", "session_id", "sessions"),
    ("project_notifications", "deploy_run_id", "deploy_runs"),
    ("project_schedules", "last_session_id", "sessions"),
    ("session_events", "parent_event_id", "session_events"),
]


@pytest.fixture(scope="module")
def b_other_project(client_b):
    """B's second project, with one row of each kind a reference can point at."""
    world = World(client_b, "B2")
    world.rows["projects"] = world.insert(BY_NAME["projects"], BY_NAME["projects"].make(world, {}))
    for name in ("project_schedules", "sessions", "deploy_runs"):
        world.rows[name] = world.insert(BY_NAME[name], BY_NAME[name].make(world, {}))
    world.rows["session_events"] = world.insert(BY_NAME["session_events"], BY_NAME["session_events"].make(world, {}))
    yield world
    world.cleanup()


@pytest.mark.parametrize("table_name,column,target", SAME_PROJECT, ids=[f"{t}.{c}" for t, c, _ in SAME_PROJECT])
def test_a_reference_cannot_cross_into_another_project_of_the_same_account(table_name, column, target, world_b, b_other_project, client_b):
    table = BY_NAME[table_name]
    payload = table.make(world_b, {column: b_other_project.ref(target)})
    assert_refused(
        lambda: client_b.table(table.name).insert(payload).execute(),
        what=f"{table.name}.{column} -> a {target} of B's OTHER project",
        allowed=REFERENCE_REFUSAL,
    )


# ---------------------------------------------------------------------------------------------------------
# anonymous callers
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_anonymous_callers_see_and_write_nothing(table, world_b, anon_client):
    try:
        rows = anon_client.table(table.name).select("*").limit(5).execute().data
    except Exception as exc:  # noqa: BLE001 — "permission denied" is as good as an empty result
        assert code_of(exc) == "42501", exc
    else:
        assert rows == [], f"{table.name}: an unauthenticated caller can read rows"
    assert_refused(
        lambda: anon_client.table(table.name).insert(table.make(world_b, {})).execute(),
        what=f"{table.name}: anonymous insert",
    )


def test_the_database_functions_clients_must_not_call_are_not_callable(world_a, client_a, client_b, anon_client):
    """The attachment state functions (0013) move rows between message states and are for the backend alone; the
    audit function (0015) is for signed-in callers only."""
    session_id = world_a.rows["sessions"]["id"]
    for who, client in (("A", client_a), ("B", client_b), ("anonymous", anon_client)):
        assert_refused(
            lambda c=client: c.rpc("claim_session_attachments", {"p_session_id": session_id, "p_ids": [], "p_token": -1}).execute(),
            what=f"{who} calling claim_session_attachments",
        )
        assert_refused(
            lambda c=client: c.rpc("release_session_attachments", {"p_session_id": session_id, "p_token": -1}).execute(),
            what=f"{who} calling release_session_attachments",
        )
    assert_refused(lambda: anon_client.rpc("rls_audit").execute(), what="anonymous calling rls_audit")


# ---------------------------------------------------------------------------------------------------------
# the shared-workspace model (§23.4)
# ---------------------------------------------------------------------------------------------------------


def test_two_projects_cannot_share_a_workspace_handle(world_a, world_b, client_b):
    """Several sessions of ONE project deliberately share its workspace (§23.4). The mirror-image guarantee is that
    two projects — above all two ACCOUNTS' projects — never name the same one: that would put one account's agent
    inside another's files. B can only write a handle string; a unique index must refuse A's."""
    a_handle = world_a.rows["project_workspaces"]["sprite_handle"]
    row = world_b.rows["project_workspaces"]
    assert_refused(
        lambda: client_b.table("project_workspaces").update({"sprite_handle": a_handle}).eq("project_id", row["project_id"]).execute(),
        what="B pointing its workspace at A's workspace handle",
        allowed=("23505", "42501"),
    )


# ---------------------------------------------------------------------------------------------------------
# the catalog guards
# ---------------------------------------------------------------------------------------------------------


def test_catalog_every_table_in_the_database_is_registered(audit):
    in_db = {t["name"] for t in audit["tables"]}
    registered = {t.name for t in TABLES} | EXEMPT_TABLES
    assert in_db - registered == set(), (
        f"tables with NO isolation tests: {sorted(in_db - registered)}. Add each to TABLES in tests/isolation_registry.py."
    )
    assert registered - in_db == set(), f"registered but not in the database (migration not applied?): {sorted(registered - in_db)}"


def test_catalog_every_table_has_row_level_security_and_a_policy(audit):
    with_policy = {p["table"] for p in audit["policies"]}
    for table in audit["tables"]:
        assert table["rls"] is True, f"{table['name']}: row-level security is OFF"
        assert table["name"] in with_policy, f"{table['name']}: RLS is on but there is no policy (nobody could use it)"


def test_catalog_every_policy_is_keyed_on_the_callers_uid(audit):
    for policy in audit["policies"]:
        assert "auth.uid()" in (policy["using"] or ""), (
            f"{policy['table']}.{policy['name']}: USING does not reference auth.uid() — a policy like `using (true)` "
            f"shows every account's rows to every other. Found: {policy['using']!r}"
        )
        if policy["check"] is not None:
            assert "auth.uid()" in policy["check"], f"{policy['table']}.{policy['name']}: WITH CHECK lacks auth.uid(): {policy['check']!r}"


def test_catalog_every_foreign_key_between_owned_tables_is_declared(audit):
    owned = set(BY_NAME)
    for fk in audit["foreign_keys"]:
        table_name, column, target = fk["table"].split(".")[-1], fk["column"], fk["references"].split(".")[-1]
        if table_name not in owned or target not in owned:
            continue  # e.g. -> auth.users: that's what `user_id` scoping IS
        table = BY_NAME[table_name]
        declared = column == table.scope or table.cross_refs.get(column) == target
        assert declared, (
            f"{table_name}.{column} -> {target} is a foreign key between two user-owned tables that "
            f"isolation_registry.py doesn't know about. Add it to cross_refs for {table_name}: the suite will then "
            "test that account B cannot point it at account A's rows."
        )
    declared_pairs = {(t.name, c) for t in TABLES for c in t.cross_refs}
    real_pairs = {(fk["table"].split(".")[-1], fk["column"]) for fk in audit["foreign_keys"]}
    assert declared_pairs <= real_pairs, f"declared cross-references with no such foreign key: {sorted(declared_pairs - real_pairs)}"


def test_catalog_no_function_is_callable_by_clients_except_the_audit(audit):
    exposed = {
        f["name"]
        for f in audit["functions"]
        if f["returns"] != "trigger" and (f["authenticated_can_execute"] or f["anon_can_execute"])
    }
    assert exposed == set(CLIENT_CALLABLE_FUNCTIONS), (
        f"functions in `public` that a signed-in or anonymous caller can execute (PostgREST exposes them as /rpc/...): "
        f"{sorted(exposed)}; expected only {sorted(CLIENT_CALLABLE_FUNCTIONS)}. REVOKE EXECUTE from public/anon/authenticated, "
        "or — if it is meant to be public — add it to CLIENT_CALLABLE_FUNCTIONS after reviewing it."
    )


# ---------------------------------------------------------------------------------------------------------
# a known gap, pinned
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN GAP (docs/PHASE6_NOTES.md): the *_ref columns that hold vault secret ids have no foreign key and a "
    "signed-in client can write them, so a row of B's can name a vault id that belongs to A. Not exploitable today "
    "(it needs A's id, a random uuid no client is shown) but it is the one place isolation rests on an id staying "
    "secret. strict=True: when this is fixed the test starts passing, which fails the run until this marker is removed.",
)
def test_known_gap_b_cannot_point_its_own_secret_at_a_vault_id_of_a(world_a, world_b, client_b):
    row = world_b.rows["project_secrets"]
    original = row["secret_ref"]
    a_ref = world_a.rows["project_secrets"]["secret_ref"]
    try:
        assert_refused(
            lambda: client_b.table("project_secrets").update({"secret_ref": a_ref}).eq("id", row["id"]).execute(),
            what="B pointing its own project_secrets.secret_ref at A's vault id",
            allowed=REFERENCE_REFUSAL,
        )
    finally:
        client_b.table("project_secrets").update({"secret_ref": original}).eq("id", row["id"]).execute()


# ---------------------------------------------------------------------------------------------------------
# last: nothing of A's moved
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("table", TABLES, ids=ids)
def test_z_after_everything_account_a_is_exactly_as_it_was(table, world_a, client_a):
    row = world_a.rows[table.name]
    after = fetch(client_a, table, row)
    assert len(after) == 1, f"{table.name}: A's row is gone"
    assert after[0] == row, f"{table.name}: A's row changed during the run: {row} -> {after[0]}"
