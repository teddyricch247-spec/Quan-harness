"""§23.7 — preview compute. See app/services/preview_runtime.py and the Phase 5.3
additions to app/services/workspace_service.py.

Same approach as test_deploy_pipeline.py: every collaborator (the Sprites SDK client,
the repositories, settings) is an in-memory double; the generated shell scripts are
also run for real in a local bash elsewhere (test_deploy_pipeline.py).

What this does NOT cover: that a real Sprite honours `http_port`, restarts a service on
wake, or reports `url`/`status`/`url_settings` the way the SDK README describes —
docs/PHASE5_3_5_4_NOTES.md lists the exact live checks.
"""
import asyncio
import types
from unittest import mock

from app.services import preview_runtime as pr
from app.services import workspace_service as ws


def _run(coro):
    return asyncio.run(coro)


def _settings(**over):
    base = dict(preview_enabled=True, preview_base_domain="preview.example.com", preview_scheme="https",
                sprites_url_host_suffix=".sprites.app", sprites_api_token="SPRITES_TOKEN")
    base.update(over)
    return types.SimpleNamespace(**base)


def _t(name, root=".", port=3000, run_cmd="npm start"):
    return {"name": name, "root": root, "stack": "node", "build_cmd": None, "run_cmd": run_cmd, "port": port}


def setup_function(_):
    pr._upstream_cache.clear()
    pr._billing_cache.clear()


# ---- entry target ---------------------------------------------------------------

def test_entry_target_is_the_only_target_when_there_is_one():
    assert pr.entry_target_name([_t("api")]) == "api"
    assert pr.entry_target_name([]) is None


def test_entry_target_prefers_a_conventionally_named_frontend():
    assert pr.entry_target_name([_t("backend"), _t("frontend")]) == "frontend"
    assert pr.entry_target_name([_t("api"), _t("Web")]) == "Web"


def test_entry_target_never_picks_an_obvious_backend_when_there_is_an_alternative():
    assert pr.entry_target_name([_t("api"), _t("dashboard")]) == "dashboard"
    assert pr.entry_target_name([_t("backend"), _t("server")]) == "backend"  # nothing but backends: first one


# ---- env precedence ---------------------------------------------------------------

def test_harness_managed_variables_always_win_over_a_secret_of_the_same_name():
    env = pr.build_target_env(3000, {"BACKEND_URL": "http://127.0.0.1:8000"}, {"PORT": "1", "BACKEND_URL": "http://evil", "STRIPE_KEY": "sk"})
    assert env == {"PORT": "3000", "BACKEND_URL": "http://127.0.0.1:8000", "STRIPE_KEY": "sk"}


def test_no_port_means_no_port_variable():
    assert "PORT" not in pr.build_target_env(None, {}, {})


def test_backend_is_ordered_before_frontend_only_when_both_exist():
    assert [t["name"] for t in pr.order_targets([_t("frontend"), _t("backend")])] == ["backend", "frontend"]
    assert [t["name"] for t in pr.order_targets([_t("b"), _t("a")])] == ["b", "a"]


# ---- scripts ------------------------------------------------------------------------

def test_service_name_and_slug_are_shell_and_name_safe():
    assert pr.slot_slug("web app/../x") == "web_app____x"
    assert pr.service_name("web app") == "qh-app-web_app"
    assert len(pr.service_name("x" * 200)) <= 60


def test_wrapper_records_pid_and_real_exit_code_and_quotes_the_command():
    w = pr.build_service_wrapper("echo 'hi there'; exit 4", "web")
    assert "echo $$ > /tmp/qh-deploy-web.pid" in w and "echo $code > /tmp/qh-deploy-web.exit" in w
    assert w.startswith("exec >> /tmp/qh-deploy-web.log 2>&1;")  # appends: a platform restart can't roll the crash output away
    assert "bash -c 'echo '\\''hi there'\\''; exit 4'" in w


def test_probe_output_parsing():
    assert pr.parse_probe_output("QH_STILL_RUNNING\n---QH_LOG---\nready\n") == (True, "ready", None)
    assert pr.parse_probe_output("QH_EXIT_CODE:3\n---QH_LOG---\nboom\n") == (False, "boom", 3)
    assert pr.parse_probe_output("QH_EXIT_CODE:\n---QH_LOG---\n") == (False, "", None)
    assert pr.parse_probe_output("") == (False, "", None)


def test_probe_checks_the_exit_file_before_kill_zero():
    # An exited-but-unreaped process still answers `kill -0`; reversed, a crashed app looked healthy.
    script = pr.build_probe_script("web", 5)
    assert script.index("exit") < script.index("kill -0")  # the exit-file branch comes first
    assert "sleep 5;" in script


# ---- upstream origin (the Sprites token must only ever go to a Sprite) ---------------

def _info(url="https://qh-abc-org.sprites.app", auth="sprite", status="warm"):
    return ws.SpriteInfo(url=url, status=status, url_auth=auth)


def _origin(info, **kw):
    async def fake(project_id):
        if isinstance(info, Exception):
            raise info
        return info

    with mock.patch.object(pr.workspace_service, "get_sprite_info", fake), mock.patch.object(pr, "get_settings", return_value=_settings()):
        return _run(pr.get_upstream_origin("p1", **kw))


def _unavailable(info):
    try:
        _origin(info, use_cache=False)
    except pr.PreviewUnavailable as exc:
        return str(exc)
    raise AssertionError("expected PreviewUnavailable")


def test_valid_sprite_url_becomes_a_validated_https_origin():
    assert _origin(_info("https://qh-abc-org.sprites.app/anything")) == "https://qh-abc-org.sprites.app"


def test_a_public_sprite_url_is_refused_not_hidden_behind_the_proxy():
    assert "public" in _unavailable(_info(auth="public"))


def test_a_url_outside_the_sprites_domain_is_refused_so_the_token_is_never_sent_there():
    assert "won't send credentials" in _unavailable(_info("https://evil.example.com"))


def test_missing_workspace_or_url_is_a_clear_message():
    assert "deploy it first" in _unavailable(None)
    assert "deploy it first" in _unavailable(_info(url=None))


def test_sprites_api_failure_is_a_clear_message_not_a_stack_trace():
    assert "couldn't be reached" in _unavailable(ws.SpriteServiceError("boom"))


def test_upstream_origin_is_cached_so_each_asset_request_does_not_cost_an_api_call():
    calls = []

    async def fake(project_id):
        calls.append(project_id)
        return _info()

    with mock.patch.object(pr.workspace_service, "get_sprite_info", fake), mock.patch.object(pr, "get_settings", return_value=_settings()):
        _run(pr.get_upstream_origin("p1"))
        _run(pr.get_upstream_origin("p1"))
        assert len(calls) == 1
        _run(pr.get_upstream_origin("p1", use_cache=False))
        assert len(calls) == 2


def test_sprites_auth_header_is_the_only_place_the_token_becomes_a_header():
    with mock.patch.object(pr, "get_settings", return_value=_settings()):
        assert pr.sprites_auth_headers() == {"Authorization": "Bearer SPRITES_TOKEN"}


# ---- subdomain allocation ----------------------------------------------------------------

def test_existing_subdomain_is_returned_unchanged():
    assert _run(pr.ensure_preview_subdomain({"id": "p", "name": "x", "preview_subdomain": "keep-me-1234"})) == "keep-me-1234"


def test_missing_subdomain_is_allocated_once_and_retried_on_collision():
    attempts = []

    async def set_if_unset(project_id, sub):
        attempts.append(sub)
        if len(attempts) == 1:
            raise RuntimeError("duplicate key value violates unique constraint")  # a collision
        return {"id": project_id, "preview_subdomain": sub}

    async def get_by_id(project_id):
        return {"id": project_id, "preview_subdomain": None}

    with mock.patch.object(pr.projects_repo, "set_preview_subdomain_if_unset", set_if_unset), mock.patch.object(pr.projects_repo, "get_by_id", get_by_id):
        sub = _run(pr.ensure_preview_subdomain({"id": "p", "name": "My App"}))
    assert sub == attempts[1] and sub.startswith("my-app-") and len(attempts) == 2


def test_losing_the_race_to_another_request_adopts_the_winners_subdomain():
    async def set_if_unset(project_id, sub):
        return None  # already set by someone else

    async def get_by_id(project_id):
        return {"id": project_id, "preview_subdomain": "winner-aaaa1111"}

    with mock.patch.object(pr.projects_repo, "set_preview_subdomain_if_unset", set_if_unset), mock.patch.object(pr.projects_repo, "get_by_id", get_by_id):
        assert _run(pr.ensure_preview_subdomain({"id": "p", "name": "x"})) == "winner-aaaa1111"


# ---- status ------------------------------------------------------------------------------------

def _status(project, latest, settings=None, billing="warm"):
    async def latest_run(project_id):
        return latest

    async def refresh(project_id):
        return {"billing_state": billing}

    with mock.patch.object(pr, "get_settings", return_value=settings or _settings()), \
         mock.patch.object(pr.deploy_runs_repo, "get_latest_for_project", latest_run), \
         mock.patch.object(pr.workspace_service, "refresh_billing_state", refresh):
        return _run(pr.get_status(project))


def test_status_when_deployed_exposes_the_stable_origin_and_billing_state():
    s = _status({"id": "p", "deploy_targets": [_t("web")], "preview_subdomain": "my-app-1a2b3c4d"}, {"status": "success"})
    assert s["can_open"] and s["origin"] == "https://my-app-1a2b3c4d.preview.example.com" and s["billing_state"] == "warm"
    assert s["entry_target"] == "web" and s["unavailable_reason"] is None


def test_status_before_any_deploy_says_to_deploy_first():
    s = _status({"id": "p", "deploy_targets": [], "preview_subdomain": "x-1111aaaa"}, None)
    assert not s["can_open"] and "Deploy the project first" in s["unavailable_reason"]


def test_status_when_the_server_isnt_configured_says_so_plainly_and_has_no_origin():
    s = _status({"id": "p", "deploy_targets": [], "preview_subdomain": "x-1111aaaa"}, {"status": "success"}, settings=_settings(preview_enabled=False))
    assert not s["configured"] and not s["can_open"] and s["origin"] is None and "PREVIEW_BASE_DOMAIN" in s["unavailable_reason"]


def test_status_never_exposes_the_sprites_own_url():
    s = _status({"id": "p", "deploy_targets": [_t("web")], "preview_subdomain": "x-1111aaaa"}, {"status": "success"})
    assert "sprites.app" not in str(s)


def test_a_failing_billing_read_does_not_take_the_status_down():
    async def boom(project_id):
        raise RuntimeError("sprites api down")

    async def latest_run(project_id):
        return {"status": "success"}

    with mock.patch.object(pr, "get_settings", return_value=_settings()), mock.patch.object(pr.deploy_runs_repo, "get_latest_for_project", latest_run), \
         mock.patch.object(pr.workspace_service, "refresh_billing_state", boom):
        s = _run(pr.get_status({"id": "p", "deploy_targets": [_t("web")], "preview_subdomain": "x-1111aaaa"}))
    assert s["billing_state"] is None and s["can_open"]


# ---- restart ----------------------------------------------------------------------------------------

def test_restart_reissues_every_target_in_order_with_current_secrets_and_only_the_entry_gets_http_port():
    launches = []

    async def fake_launch(project_id, target_dir, run_cmd, env, target_name, *, http_port=None, probe_seconds=5):
        launches.append({"name": target_name, "env": dict(env), "http_port": http_port, "cwd": target_dir})
        return True, "ok", "", None

    async def runtime_env(project_id):
        return {"STRIPE_KEY": "sk", "PORT": "9"}

    project = {"id": "p", "deploy_targets": [_t("frontend", "apps/web", 3000), _t("backend", "apps/api", 8000)]}
    with mock.patch.object(pr, "launch_and_probe", fake_launch), mock.patch.object(pr, "_runtime_env", runtime_env):
        results = _run(pr.restart_all(project))
    assert [l["name"] for l in launches] == ["backend", "frontend"] and all(r["started"] for r in results)
    assert launches[0]["http_port"] is None and launches[1]["http_port"] == 3000
    assert launches[1]["env"]["BACKEND_URL"] == "http://127.0.0.1:8000" and launches[1]["env"]["STRIPE_KEY"] == "sk"
    assert launches[0]["env"]["PORT"] == "8000"  # a secret named PORT can't redirect the app


def test_restart_with_nothing_deployed_is_a_clear_error():
    try:
        _run(pr.restart_all({"id": "p", "deploy_targets": [_t("web", run_cmd=None)]}))
    except pr.PreviewUnavailable as exc:
        assert "deploy the project first" in str(exc).lower()
        return
    raise AssertionError


def test_a_target_that_fails_to_start_is_reported_and_does_not_break_the_others():
    async def fake_launch(project_id, target_dir, run_cmd, env, target_name, *, http_port=None, probe_seconds=5):
        return (target_name != "backend"), "log", "", (None if target_name != "backend" else 1)

    async def runtime_env(project_id):
        return {}

    with mock.patch.object(pr, "launch_and_probe", fake_launch), mock.patch.object(pr, "_runtime_env", runtime_env):
        results = _run(pr.restart_all({"id": "p", "deploy_targets": [_t("frontend"), _t("backend", port=8000)]}))
    assert {r["target"]: r["started"] for r in results} == {"backend": False, "frontend": True}


# ---- launch -----------------------------------------------------------------------------------------

def test_a_failed_service_creation_is_reported_as_a_failed_start_without_probing():
    execs = []

    async def fake_exec(project_id, argv, timeout=60, cwd=None):
        execs.append(argv[-1])
        return ws.ExecResult(0, "", "")

    async def boom(*a, **kw):
        raise ws.SpriteServiceError("could not start service")

    stopped = []

    async def fake_stop(project_id, name):
        stopped.append(name)

    with mock.patch.object(pr.workspace_service, "exec_in_workspace", fake_exec), mock.patch.object(pr.workspace_service, "create_or_replace_service", boom), \
         mock.patch.object(pr.workspace_service, "stop_service", fake_stop):
        started, log, stderr, code = _run(pr.launch_and_probe("p", "/d", "npm start", {}, "web"))
    assert (started, log, code) == (False, "", None) and "could not start service" in stderr
    assert not any("QH_STILL_RUNNING" in e for e in execs)  # never probed a service that was never created


# ---- workspace_service helpers ----------------------------------------------------------------------

def test_billing_state_mapping_only_ever_yields_a_value_the_db_constraint_allows():
    for state in ("running", "warm", "cold"):
        assert ws.map_billing_state(state) == state
    for odd in ("starting", "stopped", None, "", 5):
        assert ws.map_billing_state(odd) == "running"  # over-report rather than imply "free"


class _AsyncStream:
    def __init__(self, events, hang=False):
        self.events, self.hang = list(events), hang

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.events:
            return self.events.pop(0)
        if self.hang:
            await asyncio.sleep(3600)
        raise StopAsyncIteration


def test_drain_reads_an_async_event_stream_into_text_lines():
    ev = [types.SimpleNamespace(type="started", data="svc up"), types.SimpleNamespace(type="log", data="listening")]
    assert _run(ws._drain(_AsyncStream(ev))) == ["started: svc up", "log: listening"]


def test_drain_accepts_a_plain_iterable_none_and_odd_events():
    assert _run(ws._drain(["a", 3, object()]))[:2] == ["a", "3"]
    assert _run(ws._drain(None)) == []


def test_drain_gives_up_on_a_stream_that_never_ends():
    stream = _AsyncStream([types.SimpleNamespace(type="log", data="x")], hang=True)
    assert _run(asyncio.wait_for(ws._drain(stream, max_seconds=0.05), timeout=3)) == ["log: x"]


def test_drain_respects_max_events():
    assert len(_run(ws._drain(_AsyncStream(["e"] * 50), max_events=5))) == 5


class _FakeSprite:
    def __init__(self, error=None):
        self.error, self.kwargs = error, None

    def create_service(self, name, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return _AsyncStream([types.SimpleNamespace(type="started", data=name)])


class _FakeClient:
    def __init__(self, sprite):
        self._sprite = sprite

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def sprite(self, name):
        return self._sprite


def _create(sprite, env):
    async def fake_ensure(project_id):
        return {"sprite_handle": "qh-abc"}

    with mock.patch.object(ws, "ensure_workspace", fake_ensure), mock.patch.object(ws, "_new_client", lambda: _FakeClient(sprite)):
        return _run(ws.create_or_replace_service("p", "svc", cmd="bash", args=["-c", "x"], cwd="/d", env=env, http_port=3000))


def test_create_service_passes_env_dir_and_http_port_as_structured_arguments():
    sprite = _FakeSprite()
    events = _create(sprite, {"A": "1"})
    assert sprite.kwargs == {"cmd": "bash", "args": ["-c", "x"], "env": {"A": "1"}, "dir": "/d", "http_port": 3000}
    assert events == ["started: svc"]


def test_an_sdk_error_that_echoes_the_request_never_leaks_the_secret_values_in_the_env():
    secret = "sk_live_ABCDEFGH12345678"
    sprite = _FakeSprite(error=RuntimeError(f"400 Bad Request for body {{'env': {{'STRIPE_KEY': '{secret}'}}}}"))
    try:
        _create(sprite, {"STRIPE_KEY": secret})
    except ws.SpriteServiceError as exc:
        assert secret not in str(exc) and "<secret-hidden>" in str(exc)
        return
    raise AssertionError("expected SpriteServiceError")
