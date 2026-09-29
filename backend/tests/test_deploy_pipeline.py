"""§23.5/§23.6/§23.9's orchestration, as written by app/services/deploy_pipeline.py.

Same shape as test_agent_loop_audit.py: every collaborator this module can
reach (deploy_runs_repo, projects_repo, llm_client, workspace_service) is
replaced with an in-memory double, and these tests assert on the resulting
deploy_runs rows and projects.deploy_targets state, not on any real Sprite,
LLM provider, or Supabase project. Nothing here touches a network.

What this does NOT cover: a real Sprite's actual process lifecycle (whether
`nohup ... &` really survives past the exec call that launched it) or a real
provider's response shape for the two LLM fallback calls — same "no live
infra was available to verify this against" gap this codebase's own
workspace_service.py/llm_client.py docstrings are upfront about elsewhere.
"""
import asyncio
from unittest import mock

from app.services import deploy_pipeline, llm_client, workspace_service


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


def _patched(runs: _RunsDouble, projects: _ProjectsDouble, exec_fn, llm_fn=None):
    patches = [
        mock.patch.object(deploy_pipeline, "deploy_runs_repo", runs),
        mock.patch.object(deploy_pipeline, "projects_repo", projects),
        mock.patch.object(deploy_pipeline.workspace_service, "exec_in_workspace", exec_fn),
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
            "nohup": "QH_STILL_RUNNING\n---QH_LOG---\nready on port 3000\n",
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
            "nohup": "QH_STILL_RUNNING\n---QH_LOG---\nok\n",
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


def test_dockerfile_short_circuits_to_nested_sandbox_message_no_llm_call():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p3", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double({"@@DOCKERFILE@@": "@@DOCKERFILE@@\n@@TOP_LEVEL_FILES@@\nDockerfile\n"})

    async def fail_if_called(*a, **kw):
        raise AssertionError("the LLM must never be called for a deterministic Dockerfile short-circuit")

    patches = _patched(runs, projects, exec_fn, llm_fn=fail_if_called)

    async def go():
        started = await deploy_pipeline.start_deploy("p3", "u1")
        assert started is True
        await _await_deploy_settled("p3")

    _with_patches(patches, go)
    run = next(iter(runs.rows.values()))
    assert run["status"] == "failed"
    assert run["failure_class"] == "environment"
    assert "nested container support" in run["diagnosis_text"]


# ---------------------------------------------------------------------------
# §23.9 failure diagnosis
# ---------------------------------------------------------------------------


def test_start_phase_crash_is_diagnosed_and_recorded():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p4", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    exec_fn = _exec_double(
        {
            "@@DOCKERFILE@@": '@@PACKAGE_JSON@@\n{"dependencies": {"express": "1.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n',
            "nohup": ("QH_EXIT_CODE:1\n---QH_LOG---\nError: cannot find module 'express'\n", 0),
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
            "nohup": "SHOULD_NOT_BE_CALLED",
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
    seen_env_prefixes = []

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            if "apps/api" in cwd:
                return workspace_service.ExecResult(0, "@@REQUIREMENTS_TXT@@\n@@MANAGE_PY@@\n@@TOP_LEVEL_FILES@@\n", "")
            return workspace_service.ExecResult(0, '@@PACKAGE_JSON@@\n{"dependencies": {"next": "14.0.0"}}\n@@TOP_LEVEL_FILES@@\n', "")
        if "nohup" in script:
            seen_env_prefixes.append(script)
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    patches = _patched(runs, projects, exec_fn)

    async def go():
        started = await deploy_pipeline.start_deploy("p7", "u1")
        assert started is True
        await _await_deploy_settled("p7")

    _with_patches(patches, go)

    backend_script = next(s for s in seen_env_prefixes if "apps/api" in s)
    frontend_script = next(s for s in seen_env_prefixes if "apps/web" in s)
    assert "BACKEND_URL" not in backend_script
    assert "BACKEND_URL" in frontend_script
