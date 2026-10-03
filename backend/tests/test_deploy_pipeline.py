"""§23.5/§23.6/§23.9's orchestration, as written by app/services/deploy_pipeline.py.

Same shape as test_agent_loop_audit.py: every collaborator this module can
reach (deploy_runs_repo, projects_repo, llm_client, workspace_service) is
replaced with an in-memory double, and these tests assert on the resulting
deploy_runs rows and projects.deploy_targets state, not on any real Sprite,
LLM provider, or Supabase project. Nothing here touches a network.

What this does NOT cover: a real Sprite's actual service lifecycle (that
`create_service` really restarts the app on wake, and that its `http_port` really
routes the Sprite's URL — preview_runtime.py's module docstring and
docs/PHASE5_3_5_4_NOTES.md list the live checks) or a real provider's response
shape for the two LLM fallback calls — same "no live infra was available to verify
this against" gap this codebase's own workspace_service.py/llm_client.py docstrings
are upfront about elsewhere.
"""
import asyncio
from unittest import mock

from app.services import deploy_pipeline, llm_client, preview_limitations, workspace_service


class _RunsDouble:
    """In-memory stand-in for app.repositories.deploy_runs."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next_id = 1

    async def create(self, project_id, fields):
        run_id = f"run-{self._next_id}"
        self._next_id += 1
        row = {"id": run_id, "project_id": project_id, **fields}
        self.rows[run_id] = row
        return row

    async def update(self, run_id, fields):
        self.rows[run_id].update(fields)
        return self.rows[run_id]

    async def has_running(self, project_id):
        return any(r["project_id"] == project_id and r["status"] == "running" for r in self.rows.values())

    async def fail_orphaned_running(self, project_id, message):
        closed = 0
        for r in self.rows.values():
            if r["project_id"] == project_id and r["status"] == "running":
                r.update({"status": "failed", "stderr": message})
                closed += 1
        return closed


class _ProjectsDouble:
    """In-memory stand-in for app.repositories.projects, seeded with one row."""

    def __init__(self, project: dict):
        self.project = dict(project)

    async def get_by_id(self, project_id):
        return dict(self.project)

    async def set_deploy_targets(self, project_id, targets, confirmed):
        self.project["deploy_targets"] = targets
        self.project["deploy_targets_confirmed"] = confirmed
        return dict(self.project)


def _exec_double(responses: dict[str, str]):
    """`responses` maps a substring of the script to the ExecResult.stdout it
    should return — matched in the order given, first match wins. Every
    matched call returns exit_code=0 unless the stdout value is a
    (stdout, exit_code) tuple."""

    async def _fake(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        for needle, value in responses.items():
            if needle in script:
                stdout, exit_code = value if isinstance(value, tuple) else (value, 0)
                return workspace_service.ExecResult(exit_code=exit_code, stdout=stdout, stderr="")
        return workspace_service.ExecResult(exit_code=0, stdout="", stderr="")

    return _fake


def _run(coro):
    return asyncio.run(coro)


class _NotificationsDouble:
    """In-memory stand-in for app.services.preview_notifications (Phase 5.4)."""

    def __init__(self):
        self.failures: list[tuple] = []  # (kind, diagnosis_text, run_id)
        self.env_scans: list = []  # the .env.example text each deploy handed over
        self.resolved = 0

    async def scan_missing_env(self, project_id, env_example_text, run_id):
        self.env_scans.append(env_example_text)
        return []

    async def raise_environment_failure(self, project_id, kind, diagnosis_text, run_id):
        self.failures.append((kind, diagnosis_text, run_id))

    async def resolve_after_success(self, project_id):
        self.resolved += 1

    async def context_for(self, project_id, project=None, missing=None):
        return preview_limitations.GuidanceContext(origin="https://p-1234.preview.example.com")


class _ServiceDouble:
    """Records the Sprite service calls preview_runtime makes, so tests can assert
    on what the app was started with (env, http_port, cmd) without a Sprite."""

    def __init__(self):
        self.created: list[dict] = []
        self.stopped: list[str] = []

    async def create_or_replace_service(self, project_id, name, *, cmd, args, cwd, env, http_port=None, watch_seconds=10.0):
        self.created.append({"name": name, "cmd": cmd, "args": args, "cwd": cwd, "env": dict(env), "http_port": http_port})
        return []

    async def stop_service(self, project_id, name):
        self.stopped.append(name)


def _patched(runs: _RunsDouble, projects: _ProjectsDouble, exec_fn, llm_fn=None, notes=None, services=None, secret_env=None):
    notes = notes if notes is not None else _NotificationsDouble()
    services = services if services is not None else _ServiceDouble()

    async def _no_redaction(project_id, text):
        return text

    patches = [
        mock.patch.object(deploy_pipeline, "deploy_runs_repo", runs),
        mock.patch.object(deploy_pipeline, "projects_repo", projects),
        mock.patch.object(deploy_pipeline.workspace_service, "exec_in_workspace", exec_fn),
        mock.patch.object(deploy_pipeline.workspace_service, "create_or_replace_service", services.create_or_replace_service),
        mock.patch.object(deploy_pipeline.workspace_service, "stop_service", services.stop_service),
        mock.patch.object(deploy_pipeline, "preview_notifications", notes),
        mock.patch.object(deploy_pipeline.preview_secrets_service, "get_runtime_env", mock.AsyncMock(return_value=dict(secret_env or {}))),
        mock.patch.object(deploy_pipeline.preview_secrets_service, "redact_text", _no_redaction),
        mock.patch.object(deploy_pipeline.llm_client, "resolve_credential", mock.AsyncMock(return_value=llm_client.ResolvedCredential(
            id="c1", provider="anthropic", model="claude-sonnet-4-6", api_key="k", base_url=None, extra_headers={}
        ))),
    ]
    if llm_fn is not None:
        patches.append(mock.patch.object(deploy_pipeline.llm_client, "call_llm", llm_fn))
    return patches


async def _await_deploy_settled(project_id: str, timeout: float = 2.0):
    waited = 0.0
    while deploy_pipeline.is_running(project_id) and waited < timeout:
        await asyncio.sleep(0.01)
        waited += 0.01


def _with_patches(patches, coro_factory):
    for p in patches:
        p.start()
    try:
        return _run(coro_factory())
    finally:
        for p in reversed(patches):
            p.stop()


# ---------------------------------------------------------------------------
# 'scratch' origin: no confirmation prompt, single implicit root (§23.6)
# ---------------------------------------------------------------------------


def test_scratch_project_auto_confirms_single_root_and_deploys_successfully():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p1", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double(
        {
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\npackage.json\n',
            "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nready on port 3000\n",
        }
    )
    patches = _patched(runs, projects, exec_fn)

    async def go():
        started = await deploy_pipeline.start_deploy("p1", "u1")
        assert started is True
        await _await_deploy_settled("p1")

    _with_patches(patches, go)

    assert projects.project["deploy_targets_confirmed"] is True
    assert projects.project["deploy_targets"][0]["stack"] == "nextjs"
    run = next(iter(runs.rows.values()))
    assert run["status"] == "success"
    assert run["phase"] == "healthy"


def test_already_running_deploy_is_rejected():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p1", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": True})
    exec_fn = _exec_double({})
    patches = _patched(runs, projects, exec_fn)

    async def go():
        deploy_pipeline._running_projects.add("p1")
        try:
            return await deploy_pipeline.start_deploy("p1", "u1")
        finally:
            deploy_pipeline._running_projects.discard("p1")

    result = _with_patches(patches, go)
    assert result is False


# ---------------------------------------------------------------------------
# 'imported' origin: §23.6 confirmation gate
# ---------------------------------------------------------------------------


def test_imported_project_with_ambiguous_roots_needs_confirmation_via_llm_fallback():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p2", "repo_origin": "imported", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double({"find .": "turbo.json\napps/web/package.json\n"})

    async def fake_call_llm(messages, tools, credential):
        return mock.Mock(text='{"targets": [{"name": "web", "root": "apps/web"}, {"name": "api", "root": "apps/api"}]}')

    patches = _patched(runs, projects, exec_fn, llm_fn=fake_call_llm)

    async def go():
        try:
            await deploy_pipeline.start_deploy("p2", "u1")
            return None
        except deploy_pipeline.DeployNeedsConfirmation as exc:
            return exc.proposed_targets

    proposed = _with_patches(patches, go)
    assert proposed is not None
    assert {t["name"] for t in proposed} == {"web", "api"}
    assert projects.project["deploy_targets_confirmed"] is False


def test_imported_project_single_root_still_needs_one_time_confirmation():
    # §23.6: "This detection/confirmation step is for imported repos only" —
    # unconditional on root count, not just the multi-root case. A single
    # package.json for an imported repo still stops here.
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p2b", "repo_origin": "imported", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double({"find .": "package.json\n"})
    patches = _patched(runs, projects, exec_fn)

    async def go():
        try:
            await deploy_pipeline.start_deploy("p2b", "u1")
            return None
        except deploy_pipeline.DeployNeedsConfirmation as exc:
            return exc.proposed_targets

    proposed = _with_patches(patches, go)
    assert proposed == [{"name": "app", "root": ".", "stack": None, "build_cmd": None, "run_cmd": None, "port": None}]


def test_confirmed_imported_targets_skip_redetection_of_roots():
    runs = _RunsDouble()
    projects = _ProjectsDouble(
        {
            "id": "p2c",
            "repo_origin": "imported",
            "deploy_targets": [{"name": "web", "root": "apps/web", "stack": None, "build_cmd": None, "run_cmd": None, "port": None}],
            "deploy_targets_confirmed": True,
        }
    )
    exec_fn = _exec_double(
        {
            "find .": "SHOULD_NOT_BE_CALLED",
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {}, "scripts": {"start": "node x.js"}}\n@@TOP_LEVEL_FILES@@\n',
            "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nok\n",
        }
    )
    patches = _patched(runs, projects, exec_fn)

    async def go():
        started = await deploy_pipeline.start_deploy("p2c", "u1")
        assert started is True
        await _await_deploy_settled("p2c")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["target_name"] == "web"
    assert run["status"] == "success"


# ---------------------------------------------------------------------------
# §23.6 nested sandboxing
# ---------------------------------------------------------------------------


_DOCKERFILE_ONLY_SCAN = "@@DOCKERFILE@@\n@@TOP_LEVEL_FILES@@\nDockerfile\n"
_DOCKERFILE_PLUS_NEXT_SCAN = (
    '@@DOCKERFILE@@\n@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\nDockerfile\npackage.json\n'
)


def _deploy(project_id, projects, exec_fn, llm_fn=None, **patch_kw):
    runs = _RunsDouble()
    patches = _patched(runs, projects, exec_fn, llm_fn=llm_fn, **patch_kw)

    async def go():
        assert await deploy_pipeline.start_deploy(project_id, "u1") is True
        await _await_deploy_settled(project_id)

    _with_patches(patches, go)
    return runs


def _scratch(project_id):
    return _ProjectsDouble({"id": project_id, "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})


def test_a_dockerfile_merely_existing_no_longer_blocks_a_normal_project():
    # Regression for the Phase 5.1 behaviour: ANY Dockerfile used to short-circuit to
    # "needs nested container support", so a Next.js app that happened to ship a
    # Dockerfile for production could never be previewed. §23.6 is about the repo's
    # own logic *using* Docker, not a file existing.
    notes = _NotificationsDouble()
    projects = _scratch("p3")
    exec_fn = _exec_double({"@@DOCKERFILE@@": _DOCKERFILE_PLUS_NEXT_SCAN, "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nready\n"})
    runs = _deploy("p3", projects, exec_fn, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "success" and run["stack"] == "nextjs"
    assert notes.failures == []


def test_a_detected_command_that_invokes_docker_is_a_nested_container_failure_with_no_diagnosis_call():
    notes = _NotificationsDouble()
    projects = _scratch("p3b")
    exec_fn = _exec_double({"@@DOCKERFILE@@": _DOCKERFILE_ONLY_SCAN})
    calls = []

    async def fallback_proposes_docker(messages, tools, credential):
        calls.append(messages)
        if len(calls) > 1:
            raise AssertionError("a deterministic nested-container failure must not spend a diagnosis LLM call")
        return mock.Mock(text='{"build_cmd": "docker build -t app .", "run_cmd": "docker run -p 3000:3000 app", "port": 3000}')

    runs = _deploy("p3b", projects, exec_fn, llm_fn=fallback_proposes_docker, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed" and run["failure_class"] == "environment" and run["environment_kind"] == "nested_container"
    assert "nested container support" in run["diagnosis_text"] and run["suggested_fix_prompt"] is None
    assert [f[0] for f in notes.failures] == ["nested_container"]
    # The docker commands must NOT be persisted as "the plan", or every later deploy would
    # reuse them instead of re-detecting after the person changes the repo.
    assert projects.project["deploy_targets"][0]["run_cmd"] is None


def test_fallback_prompt_tells_the_model_docker_is_unavailable():
    from app.services import deploy_detection

    prompt = deploy_detection.build_stack_detection_prompt(".", {"top_level_files": ["Dockerfile"]})
    assert "NOT available" in prompt and "Dockerfile" in prompt


def test_docker_daemon_unavailable_in_the_start_log_is_recognised_without_asking_a_model():
    notes = _NotificationsDouble()
    projects = _scratch("p3c")
    exec_fn = _exec_double({
        "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"express": "1.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n',
        "QH_STILL_RUNNING": "QH_EXIT_CODE:1\n---QH_LOG---\nError: Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n",
    })

    async def fail_if_called(*a, **kw):
        raise AssertionError("no LLM call expected")

    runs = _deploy("p3c", projects, exec_fn, llm_fn=fail_if_called, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["environment_kind"] == "nested_container" and run["failure_class"] == "environment"
    assert [f[0] for f in notes.failures] == ["nested_container"]


_EXPRESS_SCAN = '@@PACKAGE_JSON@@\n{"dependencies": {"express": "1.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n'


def _crashing(log):
    return _exec_double({"@@DOCKERFILE@@": _EXPRESS_SCAN, "QH_STILL_RUNNING": f"QH_EXIT_CODE:1\n---QH_LOG---\n{log}\n"})


def test_environment_failure_from_the_diagnosis_model_raises_a_notification_of_that_kind():
    notes = _NotificationsDouble()

    async def llm(messages, tools, credential):
        return mock.Mock(text='{"diagnosis": "Postgres refused the connection.", "failure_class": "environment", '
                              '"environment_kind": "database", "suggested_fix_prompt": "SHOULD BE DROPPED"}')

    runs = _deploy("p3d", _scratch("p3d"), _crashing("connect ECONNREFUSED 10.0.0.5:5432"), llm_fn=llm, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["failure_class"] == "environment" and run["environment_kind"] == "database"
    assert run["suggested_fix_prompt"] is None  # §23.9 point 4: never "fix" framing for an environment issue
    assert notes.failures == [("database", "Postgres refused the connection.", run["id"])]


def test_unrecognised_environment_failure_is_still_routed_as_other_not_dropped():
    notes = _NotificationsDouble()

    async def llm(messages, tools, credential):
        return mock.Mock(text='{"diagnosis": "Something about the host.", "failure_class": "environment", "suggested_fix_prompt": null}')

    runs = _deploy("p3e", _scratch("p3e"), _crashing("weird"), llm_fn=llm, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["environment_kind"] == "other" and [f[0] for f in notes.failures] == ["other"]


def test_a_build_class_failure_raises_no_notification():
    notes = _NotificationsDouble()

    async def llm(messages, tools, credential):
        return mock.Mock(text='{"diagnosis": "Syntax error.", "failure_class": "build", "environment_kind": "cors", "suggested_fix_prompt": "Fix it"}')

    runs = _deploy("p3f", _scratch("p3f"), _crashing("SyntaxError"), llm_fn=llm, notes=notes)
    run = next(iter(runs.rows.values()))
    assert run["failure_class"] == "build" and run["environment_kind"] is None and notes.failures == []


def test_with_no_llm_credential_a_recognisable_environment_failure_is_still_surfaced():
    notes = _NotificationsDouble()
    projects = _scratch("p3g")
    exec_fn = _crashing("Access to fetch at 'https://api.x.com' from origin 'https://p.preview.example.com' has been blocked by CORS policy")
    runs = _RunsDouble()
    patches = _patched(runs, projects, exec_fn, notes=notes)
    patches.append(mock.patch.object(deploy_pipeline.llm_client, "resolve_credential", mock.AsyncMock(side_effect=llm_client.NoLlmCredentialError("none"))))

    async def go():
        assert await deploy_pipeline.start_deploy("p3g", "u1") is True
        await _await_deploy_settled("p3g")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["failure_class"] == "environment" and run["environment_kind"] == "cors"
    assert [f[0] for f in notes.failures] == ["cors"]
    assert "p-1234.preview.example.com" in run["diagnosis_text"]  # the stable origin the person would allowlist


def test_a_successful_deploy_closes_failure_notifications_and_a_failed_one_does_not():
    ok_notes, bad_notes = _NotificationsDouble(), _NotificationsDouble()
    ok_exec = _exec_double({"@@DOCKERFILE@@": _NEXT_SCAN, "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nok\n"})
    _deploy("p3h", _scratch("p3h"), ok_exec, notes=ok_notes)
    assert ok_notes.resolved == 1

    async def llm(messages, tools, credential):
        return mock.Mock(text='{"diagnosis": "x", "failure_class": "build", "suggested_fix_prompt": null}')

    _deploy("p3i", _scratch("p3i"), _crashing("boom"), llm_fn=llm, notes=bad_notes)
    assert bad_notes.resolved == 0


def test_the_env_example_text_is_handed_to_the_missing_secrets_check():
    notes = _NotificationsDouble()
    scan = '@@ENV_EXAMPLE@@\nSTRIPE_KEY=sk_test_x\nDATABASE_URL=\n@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\n.env.example\npackage.json\n'
    exec_fn = _exec_double({"@@DOCKERFILE@@": scan, "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nok\n"})
    runs = _deploy("p3j", _scratch("p3j"), exec_fn, notes=notes)
    assert len(notes.env_scans) == 1 and "STRIPE_KEY" in notes.env_scans[0] and "DATABASE_URL" in notes.env_scans[0]
    assert next(iter(runs.rows.values()))["status"] == "success"  # informational: never blocks the deploy


def test_scan_script_never_glues_the_next_section_marker_onto_a_file_with_no_trailing_newline():
    # Regression (found in Phase 5.3): `cat package.json` with no final newline fused the
    # next marker onto its last line, so that section vanished from the parse — for
    # package.json that meant pnpm-lock/yarn-lock flags and the file listing were lost.
    import pathlib, subprocess, tempfile

    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "package.json").write_text('{"dependencies": {"next": "14.0.0"}}')  # note: no trailing \n
        pathlib.Path(d, "Procfile").write_text("web: node server.js")                      # nor here
        pathlib.Path(d, "pnpm-lock.yaml").write_text("lockfileVersion: 9")
        pathlib.Path(d, ".env.example").write_text("STRIPE_KEY=abc\nLAST_NO_NEWLINE=1")    # nor here
        out = subprocess.run(["bash", "-c", deploy_pipeline._ROOT_SCAN_SCRIPT], cwd=d, capture_output=True, text=True).stdout
    parsed = deploy_pipeline._parse_root_scan(out)
    assert parsed.get("pnpm_lock") is True                       # the flag AFTER package.json/Procfile survived
    assert "next" in parsed["package_json"] and "@@" not in parsed["package_json"]
    assert "web: node server.js" in parsed["procfile"] and "@@" not in parsed["procfile"]
    assert "LAST_NO_NEWLINE=1" in parsed["env_example"] and "@@" not in parsed["env_example"]
    assert "package.json" in parsed["top_level_files"] and ".env.example" in parsed["top_level_files"]


# ---------------------------------------------------------------------------
# §23.9 failure diagnosis
# ---------------------------------------------------------------------------


def test_start_phase_crash_is_diagnosed_and_recorded():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p4", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double(
        {
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"express": "1.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n',
            "QH_STILL_RUNNING": ("QH_EXIT_CODE:1\n---QH_LOG---\nError: cannot find module 'express'\n", 0),
        }
    )

    async def fake_call_llm(messages, tools, credential):
        return mock.Mock(
            text='{"diagnosis": "express is not installed", "failure_class": "build", '
            '"suggested_fix_prompt": "Run npm install express"}'
        )

    patches = _patched(runs, projects, exec_fn, llm_fn=fake_call_llm)

    async def go():
        started = await deploy_pipeline.start_deploy("p4", "u1")
        assert started is True
        await _await_deploy_settled("p4")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed" and run["phase"] == "start"
    assert run["exit_code"] == 1
    assert run["failure_class"] == "build"
    assert run["suggested_fix_prompt"] == "Run npm install express"


def test_build_phase_failure_is_diagnosed_and_never_reaches_start():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p5", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double(
        {
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"next": "1.0.0"}}\n@@TOP_LEVEL_FILES@@\n',
            "npm install && npm run build": ("SyntaxError: unexpected token", 1),
            "QH_STILL_RUNNING": "SHOULD_NOT_BE_CALLED",
        }
    )

    async def fake_call_llm(messages, tools, credential):
        return mock.Mock(text='{"diagnosis": "syntax error in the build", "failure_class": "build", "suggested_fix_prompt": "fix the syntax error"}')

    patches = _patched(runs, projects, exec_fn, llm_fn=fake_call_llm)

    async def go():
        started = await deploy_pipeline.start_deploy("p5", "u1")
        assert started is True
        await _await_deploy_settled("p5")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed" and run["phase"] == "build"
    assert run["diagnosis_text"] == "syntax error in the build"


def test_diagnosis_failure_does_not_block_the_raw_log_from_being_saved():
    # §23.9 point 2's own best-effort framing: a diagnosis call that itself
    # fails must never erase or block the raw stdout/stderr/exit_code
    # (point 1) already captured.
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p6", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double(
        {
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"next": "1.0.0"}}\n@@TOP_LEVEL_FILES@@\n',
            "npm install && npm run build": ("boom", 1),
        }
    )

    async def broken_call_llm(messages, tools, credential):
        raise llm_client.LlmCallFailedError("provider is down")

    patches = _patched(runs, projects, exec_fn, llm_fn=broken_call_llm)

    async def go():
        started = await deploy_pipeline.start_deploy("p6", "u1")
        assert started is True
        await _await_deploy_settled("p6")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed"
    assert run["stdout"] == "boom"
    assert run["exit_code"] == 1
    assert run.get("diagnosis_text") is None  # best-effort — absent, not a placeholder


# ---------------------------------------------------------------------------
# §23.6 monorepo BACKEND_URL injection heuristic
# ---------------------------------------------------------------------------


def test_backend_target_deploys_before_frontend_and_frontend_gets_backend_url():
    runs = _RunsDouble()
    projects = _ProjectsDouble(
        {
            "id": "p7",
            "repo_origin": "imported",
            "deploy_targets": [
                {"name": "frontend", "root": "apps/web", "stack": None, "build_cmd": None, "run_cmd": None, "port": None},
                {"name": "backend", "root": "apps/api", "stack": None, "build_cmd": None, "run_cmd": None, "port": None},
            ],
            "deploy_targets_confirmed": True,
        }
    )
    services = _ServiceDouble()

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            if "apps/api" in cwd:
                return workspace_service.ExecResult(0, "@@REQUIREMENTS_TXT@@\n@@MANAGE_PY@@\n@@TOP_LEVEL_FILES@@\n", "")
            return workspace_service.ExecResult(0, '@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\n', "")
        if "QH_STILL_RUNNING" in script:
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    patches = _patched(runs, projects, exec_fn, services=services)

    async def go():
        started = await deploy_pipeline.start_deploy("p7", "u1")
        assert started is True
        await _await_deploy_settled("p7")

    _with_patches(patches, go)

    by_name = {c["name"]: c for c in services.created}
    assert [c["name"] for c in services.created] == ["qh-app-backend", "qh-app-frontend"]  # backend starts first
    assert "BACKEND_URL" not in by_name["qh-app-backend"]["env"]
    assert by_name["qh-app-frontend"]["env"]["BACKEND_URL"].startswith("http://127.0.0.1:")
    # A Sprite's URL routes to ONE port: only the entry target (the frontend) declares it.
    assert by_name["qh-app-backend"]["http_port"] is None
    assert by_name["qh-app-frontend"]["http_port"] == 3000


# ---------------------------------------------------------------------------
# Regression tests for bugs found in review
# ---------------------------------------------------------------------------

_NEXT_SCAN = '@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\npackage.json\n'


def test_orphaned_running_row_does_not_block_a_new_deploy():
    # A row left 'running' by a restart/crash used to make has_running() return True
    # forever, so every later deploy of that project was rejected with a 409.
    runs = _RunsDouble()
    runs.rows["old"] = {"id": "old", "project_id": "p8", "status": "running"}
    projects = _ProjectsDouble({"id": "p8", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": True})
    projects.project["deploy_targets"] = [{"name": "app", "root": ".", "stack": None, "build_cmd": None, "run_cmd": None, "port": None}]
    exec_fn = _exec_double({"@@DOCKERFILE@@": _NEXT_SCAN, "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nok\n"})
    patches = _patched(runs, projects, exec_fn)

    async def go():
        started = await deploy_pipeline.start_deploy("p8", "u1")
        assert started is True
        await _await_deploy_settled("p8")

    _with_patches(patches, go)
    assert runs.rows["old"]["status"] == "failed"
    assert any(r["status"] == "success" for r in runs.rows.values())


def test_unexpected_crash_in_pipeline_never_leaves_a_run_stuck_running():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p9", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})

    async def exploding_exec(project_id, argv, timeout=60, cwd=None):
        raise RuntimeError("sprite unreachable")

    patches = _patched(runs, projects, exploding_exec)

    async def go():
        assert await deploy_pipeline.start_deploy("p9", "u1") is True
        await _await_deploy_settled("p9")

    _with_patches(patches, go)
    assert runs.rows, "a run row should have been created before the crash"
    assert all(r["status"] != "running" for r in runs.rows.values())
    assert not deploy_pipeline.is_running("p9")


def test_raw_log_is_saved_before_the_diagnosis_call_starts():
    # §23.9 point 1 before point 2: the Console tab must be able to show the raw log
    # while the diagnosis is still being produced.
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p10", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double({"@@DOCKERFILE@@": _NEXT_SCAN, "npm install && npm run build": ("boom", 1)})
    seen_at_diagnosis_time = {}

    async def fake_call_llm(messages, tools, credential):
        row = next(iter(runs.rows.values()))
        seen_at_diagnosis_time.update({"status": row["status"], "stdout": row.get("stdout"), "exit_code": row.get("exit_code")})
        return mock.Mock(text='{"diagnosis": "d", "failure_class": "build", "suggested_fix_prompt": "f"}')

    patches = _patched(runs, projects, exec_fn, llm_fn=fake_call_llm)

    async def go():
        assert await deploy_pipeline.start_deploy("p10", "u1") is True
        await _await_deploy_settled("p10")

    _with_patches(patches, go)
    assert seen_at_diagnosis_time == {"status": "failed", "stdout": "boom", "exit_code": 1}


def test_unexpected_error_inside_diagnosis_does_not_lose_the_raw_log_or_crash_the_deploy():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p11", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double({"@@DOCKERFILE@@": _NEXT_SCAN, "npm install && npm run build": ("boom", 1)})

    async def weird_call_llm(messages, tools, credential):
        raise KeyError("something the pipeline didn't anticipate")

    patches = _patched(runs, projects, exec_fn, llm_fn=weird_call_llm)

    async def go():
        assert await deploy_pipeline.start_deploy("p11", "u1") is True
        await _await_deploy_settled("p11")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed" and run["stdout"] == "boom"


def test_service_launch_stops_the_previous_process_passes_the_directory_structurally_and_records_exit_code():
    from app.services import preview_runtime

    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p12", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": True})
    projects.project["deploy_targets"] = [{"name": "web app", "root": "my dir", "stack": None, "build_cmd": None, "run_cmd": None, "port": None}]
    services = _ServiceDouble()
    scripts = []

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            return workspace_service.ExecResult(0, _NEXT_SCAN, "")
        scripts.append(script)
        if "QH_STILL_RUNNING" in script:
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    patches = _patched(runs, projects, exec_fn, services=services)

    async def go():
        assert await deploy_pipeline.start_deploy("p12", "u1") is True
        await _await_deploy_settled("p12")

    _with_patches(patches, go)
    svc = services.created[0]
    assert svc["name"] == "qh-app-web_app" and svc["cwd"] == "/home/sprite/repo/my dir"  # a path with a space is data, not shell text
    wrapper = svc["args"][-1]
    assert "echo $code > /tmp/qh-deploy-web_app.exit" in wrapper  # the app's real exit code, not `wait` from a foreign shell
    assert "echo $$ > /tmp/qh-deploy-web_app.pid" in wrapper
    assert services.stopped[0] == "qh-app-web_app"  # any previous service of this target is stopped first
    reset = next(sc for sc in scripts if "kill -- -$P" in sc)
    assert "/tmp/qh-deploy-web_app.pid" in reset and reset.index("kill -- -$P") < reset.index("rm -f")  # stopped before its files are removed


def test_generic_node_project_gets_a_port_injected_as_dollar_port():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p13", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    services = _ServiceDouble()
    node_scan = '@@PACKAGE_JSON@@\n{"dependencies": {"express": "4.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n'
    exec_fn = _exec_double({"@@DOCKERFILE@@": node_scan, "QH_STILL_RUNNING": "QH_STILL_RUNNING\n---QH_LOG---\nok\n"})
    patches = _patched(runs, projects, exec_fn, services=services)

    async def go():
        assert await deploy_pipeline.start_deploy("p13", "u1") is True
        await _await_deploy_settled("p13")

    _with_patches(patches, go)
    assert services.created[0]["env"]["PORT"] == "3000"
    assert services.created[0]["http_port"] == 3000  # a single target is the entry target
    assert projects.project["deploy_targets"][0]["port"] == 3000


def test_preview_secrets_reach_only_the_service_env_never_a_command_line():
    secret = "sk_live_SUPERSECRETVALUE_123456"
    services = _ServiceDouble()
    argvs = []

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        argvs.append(list(argv))
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            return workspace_service.ExecResult(0, _NEXT_SCAN, "")
        if "QH_STILL_RUNNING" in script:
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    _deploy("p14", _scratch("p14"), exec_fn, services=services, secret_env={"STRIPE_KEY": secret, "PORT": "1"})
    env = services.created[0]["env"]
    assert env["STRIPE_KEY"] == secret                       # it does reach the running app...
    assert env["PORT"] == "3000"                             # ...but a secret can never override a harness-managed variable
    flattened = [a for argv in argvs for a in argv] + [a for c in services.created for a in c["args"]]
    assert not any(secret in a for a in flattened)           # ...and it appears in NO command line, ever


def test_stored_logs_and_the_diagnosis_prompt_never_contain_a_preview_secret_value():
    from app.services import secret_redaction

    secret = "sk_live_SUPERSECRETVALUE_123456"
    prompts = []

    async def real_redact(project_id, text):
        return secret_redaction.redact(text, {"STRIPE_KEY": secret})

    async def llm(messages, tools, credential):
        prompts.append(messages[0]["content"])
        return mock.Mock(text='{"diagnosis": "Used key " , "failure_class": "build", "suggested_fix_prompt": null}')

    exec_fn = _crashing(f"Error: auth failed for key {secret}")
    runs = _RunsDouble()
    projects = _scratch("p15")
    patches = _patched(runs, projects, exec_fn, llm_fn=llm) + [
        mock.patch.object(deploy_pipeline.preview_secrets_service, "redact_text", real_redact)
    ]

    async def go():
        assert await deploy_pipeline.start_deploy("p15", "u1") is True
        await _await_deploy_settled("p15")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert secret not in run["stdout"] and secret not in run["stderr"] and "<secret-hidden>" in run["stdout"]
    assert prompts and not any(secret in p for p in prompts)  # never reached the diagnosis model either


# ---------------------------------------------------------------------------
# The generated start script, executed for real in a local bash (no Sprite needed)
# ---------------------------------------------------------------------------


def _ancestor_pids() -> set[int]:
    """This process and every ancestor. Excluded from the argv scan below because an
    ancestor is whatever LAUNCHED the test run, and a launcher (a shell with a heredoc,
    a CI step) can legitimately contain the test's own literal secret string in its argv.
    That would be a false positive about the harness, not a leak from the app."""
    import os

    pids, pid = set(), os.getpid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        try:
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return pids


class _LocalServiceRuntime:
    """A stand-in for the Sprite service runtime, running the REAL generated wrapper in a
    real local bash: `create_or_replace_service` replaces any previous process of that
    name (as the platform does) and starts `cmd args` detached with `env`; stop kills it.
    What it cannot emulate is the platform's own restart-on-wake — that is a live check."""

    def __init__(self):
        self.procs = {}
        self.argvs = []

    def _kill(self, name):
        import os, signal

        proc = self.procs.pop(name, None)
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

    async def create_or_replace_service(self, project_id, name, *, cmd, args, cwd, env, http_port=None, watch_seconds=10.0):
        import os, subprocess

        self._kill(name)
        proc = subprocess.Popen([cmd, *args], cwd=cwd, env={**os.environ, **env}, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs[name] = proc
        self.argvs.append([cmd, *args])
        return []

    async def stop_service(self, project_id, name):
        self._kill(name)


def test_service_wrapper_in_a_real_shell_reports_crash_exit_code_replaces_previous_process_and_keeps_secrets_out_of_argv():
    import os
    import pathlib
    import shutil
    import subprocess
    import tempfile

    if shutil.which("bash") is None:
        return  # nothing to run it in

    tmp = tempfile.TemporaryDirectory()
    repo = pathlib.Path(tmp.name) / "repo"
    (repo / "my dir").mkdir(parents=True)
    runtime = _LocalServiceRuntime()

    async def local_exec(project_id, argv, timeout=60, cwd=None):
        r = subprocess.run(["bash", "-c", argv[-1]], capture_output=True, text=True, timeout=timeout)
        return workspace_service.ExecResult(exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr)

    slot = f"qhtest{os.getpid()}"
    pid_file = f"/tmp/qh-deploy-{slot}.pid"
    saved = deploy_pipeline.PROBE_SECONDS
    deploy_pipeline.PROBE_SECONDS = 1
    target_dir = f"{repo}/my dir"
    secret = "hunter2-SECRET-value"

    async def go():
        with mock.patch.object(deploy_pipeline.workspace_service, "exec_in_workspace", local_exec), \
             mock.patch.object(deploy_pipeline.workspace_service, "create_or_replace_service", runtime.create_or_replace_service), \
             mock.patch.object(deploy_pipeline.workspace_service, "stop_service", runtime.stop_service):
            crashed = await deploy_pipeline._start_and_probe("p", target_dir, "echo boom; exit 3", {}, slot)
            first = await deploy_pipeline._start_and_probe("p", target_dir, 'echo "got:$MY_SECRET"; sleep 30', {"MY_SECRET": secret}, slot)
            old_pid = open(pid_file).read().strip()
            # While it runs: the secret is in its environment, and in NO process's command line.
            environ = open(f"/proc/{old_pid}/environ", "rb").read().decode(errors="ignore")
            ancestors = _ancestor_pids()
            cmdlines = []
            for pid in os.listdir("/proc"):
                if pid.isdigit() and int(pid) not in ancestors:
                    try:
                        cmdlines.append(open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="ignore"))
                    except OSError:
                        pass  # the process exited between listdir and open
            second = await deploy_pipeline._start_and_probe("p", target_dir, "echo up2; sleep 30", {}, slot)
            new_pid = open(pid_file).read().strip()
            return crashed, first, second, old_pid, new_pid, environ, cmdlines

    try:
        crashed, first, second, old_pid, new_pid, environ, cmdlines = _run(go())
    finally:
        deploy_pipeline.PROBE_SECONDS = saved
        runtime._kill(f"qh-app-{slot}")
        subprocess.run(["bash", "-c", f"kill -- -$(cat {pid_file}) 2>/dev/null; rm -f /tmp/qh-deploy-{slot}.*"])
        tmp.cleanup()

    assert crashed == (False, "boom", "", 3)  # a crashed app is reported as crashed, with its real exit code
    assert first[0] is True and "got:" + secret in first[1]  # the env actually reached the process
    assert second[0] is True and old_pid != new_pid
    assert subprocess.run(["kill", "-0", old_pid], capture_output=True).returncode != 0  # redeploy replaced it
    assert f"MY_SECRET={secret}" in environ                  # it IS in the app's environment...
    assert not any(secret in c for c in cmdlines)            # ...and in no process's argv (what `ps` would show)
    assert not any(secret in a for argv in runtime.argvs for a in argv)


