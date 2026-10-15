"""
Phase 6.2 (§5, Implementation Order step 20) — the isolation verification, direct-API-call path.

    "There must be NO PATH — UI, direct API call, or raw RLS-scoped query — by which one can see or affect
     anything belonging to the other."

test_isolation_matrix.py is the raw-query path. This is the backend's own HTTP surface: the real FastAPI app, run
in-process, called with account B's real access token against the ids of rows account A really owns. The backend
uses the service role (RLS is not what protects this path — every route's own ownership check is), so this is the
only place those checks are exercised end to end against a real database.

THE SWEEP is generated from the app's own route table, so a route added next month is covered without anyone
remembering to list it:
  * every route that takes an id in its path is called as B, with every kind of A's resource that id could be, for
    every method it supports. The answer must never be a success, never a server error, and never contain anything of
    A's (names, ids). A route whose only answer is "422 invalid body" proves little, so the routes that take a body
    and matter most (messages, interrupts, attachments, approvals) are given a valid one.
  * every route with NO path id (the list endpoints) is called as B; nothing of A's may appear in any of them.
  * the CONTROL: account A must reach real handlers and succeed on its own database-only reads (CONTROL_READS) —
    otherwise a wall of 404s would look identical to a working defence.
  * NOTE: if this file ever HANGS, the cause is almost certainly B reaching `/sessions/{id}/stream` on a session that
    is not its own: a stream that opens never ends (and the in-process TestClient waits for it). Correctly, B gets a 404.
  * unauthenticated calls to the same routes are refused.
  * afterwards A's rows are exactly as they were.
A new id parameter the sweep doesn't recognise FAILS the run (see PARAM_RESOURCES) rather than being skipped.

Needs the env vars in conftest.py plus SUPABASE_SERVICE_ROLE_KEY (and whatever else app.config requires): it runs the
backend. Point it at a dedicated test project — never at production (the workflow's note explains why). Skips
locally when the backend env is missing; FAILS when ISOLATION_REQUIRED=1.
"""
import os
import re

import pytest

BACKEND_ENV = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
TINY_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

# path parameter -> the tables whose rows (of account A) it could name. An id parameter that is not here and does not
# end up in NOT_OWNERSHIP fails test_every_id_parameter_in_the_route_table_is_understood: add it, don't skip it.
PARAM_RESOURCES: dict[str, tuple[str, ...]] = {
    "project_id": ("projects",),
    "session_id": ("sessions",),
    "approval_id": ("approval_requests",),
    "checkpoint_id": ("checkpoints",),
    "attachment_id": ("session_attachments",),
    "event_id": ("session_events",),
    "secret_id": ("project_secrets", "preview_secrets"),
    "server_id": ("mcp_servers",),
    "connector_id": ("mcp_servers",),
    "mcp_server_id": ("mcp_servers",),
    "credential_id": ("llm_credentials", "github_credentials"),
    "llm_credential_id": ("llm_credentials",),
    "github_credential_id": ("github_credentials",),
    "note_id": ("project_knowledge",),
    "knowledge_id": ("project_knowledge",),
    "schedule_id": ("project_schedules",),
    "run_id": ("deploy_runs",),
    "deploy_id": ("deploy_runs",),
    "deploy_run_id": ("deploy_runs",),
    "notification_id": ("project_notifications",),
    "id": ("projects", "sessions", "mcp_servers", "llm_credentials", "github_credentials", "project_schedules", "deploy_runs"),
}
# Named (not id) parameters that identify A's rows by a name: filled from the row's own name column.
PARAM_NAMES: dict[str, tuple[tuple[str, str], ...]] = {
    "name": (("project_secrets", "name"), ("preview_secrets", "name")),
    "secret_name": (("project_secrets", "name"), ("preview_secrets", "name")),
    "tool_name": (("mcp_tool_overrides", "tool_name"),),
}
NOT_OWNERSHIP: frozenset[str] = frozenset({"provider", "path", "full_path", "token", "state", "filename", "kind"})

CURATED_BODIES = {
    ("POST", "/sessions/{session_id}/messages"): {"text": "isolation probe"},
    ("POST", "/sessions/{session_id}/interrupt"): {"text": "isolation probe"},
    ("POST", "/sessions/{session_id}/attachments"): {"filename": "probe.png", "media_type": "image/png", "data_base64": TINY_PNG},
    ("POST", "/approvals/{approval_id}/resolve"): {"approved": True},
    ("PATCH", "/projects/{project_id}"): {"name": "hijacked"},
    ("PATCH", "/sessions/{session_id}"): {"title": "hijacked"},
}
SKIPPED_PATHS = ("/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect")
PARAM = re.compile(r"{(\w+)(?::\w+)?}")


def _need_backend() -> None:
    missing = [n for n in BACKEND_ENV if not os.environ.get(n)]
    if not missing:
        return
    message = f"the API isolation tests run the backend and need: {', '.join(missing)}"
    if os.environ.get("ISOLATION_REQUIRED") == "1":
        pytest.fail(message + " (ISOLATION_REQUIRED=1)")
    pytest.skip(message)


@pytest.fixture(scope="module")
def app_routes():
    _need_backend()
    from fastapi.routing import APIRoute

    from app.main import app

    return [r for r in app.routes if isinstance(r, APIRoute) and r.path not in SKIPPED_PATHS]


@pytest.fixture(scope="module")
def api(app_routes):
    from fastapi.testclient import TestClient

    from app.main import app

    # No `with`: the lifespan (the scheduler loop) must not start. raise_server_exceptions=False so a crash is a 500
    # response the test can assert on, not an exception that hides which route it was.
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def token_a(client_a):
    return client_a.auth.get_session().access_token


@pytest.fixture(scope="module")
def token_b(client_b):
    return client_b.auth.get_session().access_token


def _headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def _param_values(name: str, world) -> list[str] | None:
    """Every value `name` could take for account `world` (all of them A's), or None if it isn't an ownership id."""
    if name in PARAM_RESOURCES:
        return [str(world.rows[t]["id"]) for t in PARAM_RESOURCES[name] if t in world.rows]
    if name in PARAM_NAMES:
        return [str(world.rows[t][col]) for t, col in PARAM_NAMES[name] if t in world.rows]
    if name in NOT_OWNERSHIP:
        return ["x"]
    return None


def _calls(routes, world):
    """(method, template, url) for every route+method with at least one path parameter, once per combination of the
    values its parameters could take (bounded)."""
    import itertools

    for route in routes:
        names = PARAM.findall(route.path)
        if not names:
            continue
        pools = [_param_values(n, world) or ["x"] for n in names]
        for combo in itertools.islice(itertools.product(*pools), 8):
            url = route.path
            for n, v in zip(names, combo):
                url = re.sub(r"{" + n + r"(?::\w+)?}", v, url)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path, url


def _send(api, method, template, url, token):
    kwargs = {"headers": _headers(token)}
    body = CURATED_BODIES.get((method, template))
    if method in ("POST", "PUT", "PATCH"):
        kwargs["json"] = body if body is not None else {}
    return api.request(method, url, **kwargs)


def _a_strings(world_a) -> list[str]:
    # uuids only: the identity columns' small integers would match unrelated text and cry wolf
    ids = [str(row[c]) for row in world_a.rows.values() for c in ("id", "project_id", "session_id") if len(str(row.get(c) or "")) >= 32]
    return [world_a.tag, *dict.fromkeys(ids)]


def _assert_nothing_of_a(response, strings, what):
    text = response.text
    for s in strings:
        assert s not in text, f"{what}: the response to account B contains {s!r} (a value of account A's). Body: {text[:300]}"


# ---------------------------------------------------------------------------------------------------------


def _unknown_id_params(route) -> list[str]:
    """Path parameters that look like identifiers of an account's data but that the sweep has no mapping for."""
    known = set(PARAM_RESOURCES) | set(PARAM_NAMES) | NOT_OWNERSHIP
    return [n for n in PARAM.findall(route.path) if n not in known and (n == "id" or n.endswith("_id") or n.endswith("_name"))]


def test_every_id_parameter_in_the_route_table_is_understood(app_routes):
    unknown = sorted({n for r in app_routes for n in _unknown_id_params(r)})
    assert unknown == [], (
        f"path parameters the sweep does not know how to fill: {unknown}. Add each to PARAM_RESOURCES (an id of one of "
        "account A's rows), PARAM_NAMES, or — only if it does not identify an account's data — NOT_OWNERSHIP."
    )


# The control group deliberately does NOT sweep every GET as the real owner: some routes, called with a valid project or
# session, do real work (the SSE stream never ends and Starlette's TestClient waits for the whole response; workspace and
# preview routes call out to the sandbox platform). These are the database-only reads — enough to prove the harness
# reaches real handlers. (The B sweep below is safe to run over everything: ownership is checked before any of that.)
CONTROL_READS = (
    "/projects/{project_id}",
    "/projects/{project_id}/sessions",
    "/sessions/{session_id}",
    "/sessions/{session_id}/events",
    "/sessions/{session_id}/approvals/pending",
)


def test_the_control_group_account_a_really_reaches_its_own_data(api, app_routes, world_a, token_a):
    """If account A's own calls mostly fail, B's 404s prove nothing. A must get real successes on its own rows."""
    present = [r.path for r in app_routes if r.path in CONTROL_READS and "GET" in r.methods]
    assert len(present) >= 2, f"none of the expected database-only GET routes exist any more ({CONTROL_READS}); update CONTROL_READS"
    ok = {}
    for path in present:
        url = path.replace("{project_id}", str(world_a.rows["projects"]["id"])).replace("{session_id}", str(world_a.rows["sessions"]["id"]))
        ok[path] = api.get(url, headers=_headers(token_a)).status_code
    assert sum(1 for code in ok.values() if code == 200) >= 2, f"account A reached too few of its own routes: {ok}"
    events = api.get(f"/sessions/{world_a.rows['sessions']['id']}/events", headers=_headers(token_a))
    assert events.status_code == 200 and any(world_a.tag in str(e) for e in events.json()), "A cannot read its own session events"


def test_b_cannot_reach_any_route_with_a_resource_of_a(api, app_routes, world_a, token_b):
    strings = _a_strings(world_a)
    exercised, unexercised, failures = 0, [], []
    for method, template, url in _calls(app_routes, world_a):
        response = _send(api, method, template, url, token_b)
        status = response.status_code
        if 200 <= status < 300 or status >= 500:
            failures.append(f"{method} {url} -> {status}: {response.text[:200]}")
            continue
        _assert_nothing_of_a(response, strings, f"{method} {url}")
        if status == 422:
            unexercised.append(f"{method} {template}")  # refused for its body, before the ownership check could run
        else:
            exercised += 1
    assert failures == [], "account B got a success (or a crash) on account A's resources:\n" + "\n".join(failures)
    assert exercised > 0
    # Not a failure, but the honest number: how many (method, route) pairs were refused only for an invalid body.
    print(f"\nAPI sweep: {exercised} calls reached an ownership check; {len(set(unexercised))} routes answered 422 to an empty body (add one to CURATED_BODIES to test them): {sorted(set(unexercised))}")


def test_b_sees_nothing_of_a_on_any_list_endpoint(api, app_routes, world_a, token_b):
    strings = _a_strings(world_a)
    for route in app_routes:
        if PARAM.findall(route.path) or "GET" not in route.methods or route.path.endswith("/stream"):
            continue
        response = api.get(route.path, headers=_headers(token_b))
        assert response.status_code < 500, f"GET {route.path} -> {response.status_code}: {response.text[:200]}"
        _assert_nothing_of_a(response, strings, f"GET {route.path}")


# Routes that are meant to answer a caller with no Authorization header (e.g. one authenticated by a token in its own
# path). Empty: add "METHOD /path/{template}" here, deliberately, after reviewing why.
PUBLIC_BY_DESIGN: frozenset[str] = frozenset()


def test_unauthenticated_calls_are_refused(api, app_routes, world_a):
    leaks = []
    for method, template, url in _calls(app_routes, world_a):
        if f"{method} {template}" in PUBLIC_BY_DESIGN:
            continue
        status = _send(api, method, template, url, None).status_code
        if status not in (401, 403):
            leaks.append(f"{method} {url} -> {status}")
    assert leaks == [], "routes that answered a caller with no token with something other than 401/403 (if one is public on purpose, add it to PUBLIC_BY_DESIGN):\n" + "\n".join(leaks)


def test_a_is_exactly_as_it_was_after_the_sweep(world_a, client_a):
    from tests.isolation_registry import TABLES

    for table in TABLES:
        row = world_a.rows[table.name]
        query = client_a.table(table.name).select("*")
        for column in table.pk:
            query = query.eq(column, row[column])
        after = query.execute().data
        assert len(after) == 1, f"{table.name}: A's row is gone after account B's API sweep"
        assert after[0] == row, f"{table.name}: A's row was changed by account B's API sweep: {row} -> {after[0]}"


def test_b_creating_sessions_never_touches_a_sessions(api, app_routes, world_a, world_b, token_b, client_a):
    """The per-project cap on writable sessions (§23.4) demotes the OLDEST ones in a project. It must only ever look
    at that project: B filling its own project with sessions cannot flip any of A's to read-only."""
    create = next((r for r in app_routes if re.fullmatch(r"/projects/{project_id}/sessions", r.path) and "POST" in r.methods), None)
    if create is None:
        pytest.skip("no POST /projects/{project_id}/sessions route to drive the cap with")
    before = client_a.table("sessions").select("id,read_only,read_only_reason").eq("project_id", world_a.rows["projects"]["id"]).execute().data
    created = 0
    for _ in range(4):
        response = api.post(f"/projects/{world_b.rows['projects']['id']}/sessions", json={"title": f"{world_b.tag}-cap"}, headers=_headers(token_b))
        if 200 <= response.status_code < 300:
            created += 1
    if created == 0:
        pytest.skip("could not create sessions through the API in this environment (it may need GitHub)")
    after = client_a.table("sessions").select("id,read_only,read_only_reason").eq("project_id", world_a.rows["projects"]["id"]).execute().data
    assert sorted(before, key=lambda r: r["id"]) == sorted(after, key=lambda r: r["id"])
