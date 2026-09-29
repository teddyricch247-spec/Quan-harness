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
    exec_fn = _exec_double({"@@DOCKERFILE@@": _NEXT_SCAN, "nohup": "QH_STILL_RUNNING\n---QH_LOG---\nok\n"})
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


def test_start_script_stops_the_previous_process_quotes_the_directory_and_records_exit_code():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p12", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": True})
    projects.project["deploy_targets"] = [{"name": "web app", "root": "my dir", "stack": None, "build_cmd": None, "run_cmd": None, "port": None}]
    scripts = []

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            return workspace_service.ExecResult(0, _NEXT_SCAN, "")
        if "nohup" in script:
            scripts.append(script)
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    patches = _patched(runs, projects, exec_fn)

    async def go():
        assert await deploy_pipeline.start_deploy("p12", "u1") is True
        await _await_deploy_settled("p12")

    _with_patches(patches, go)
    script = scripts[0]
    assert "kill -- -$(cat /tmp/qh-deploy-web_app.pid)" in script  # previous deploy of this target is stopped first
    assert "cd '/home/sprite/repo/my dir'" in script  # a directory with a space is quoted, not split
    assert "echo $? > /tmp/qh-deploy-web_app.exit" in script  # real exit code, not `wait` from a foreign shell
    assert "wait $(cat" not in script


def test_generic_node_project_gets_a_port_injected_as_dollar_port():
    runs = _RunsDouble()
    projects = _ProjectsDouble({"id": "p13", "repo_origin": "scratch", "deploy_targets": [], "deploy_targets_confirmed": False})
    scripts = []
    node_scan = '@@PACKAGE_JSON@@\n{"dependencies": {"express": "4.0.0"}, "scripts": {"start": "node server.js"}}\n@@TOP_LEVEL_FILES@@\n'

    async def exec_fn(project_id, argv, timeout=60, cwd=None):
        script = argv[-1]
        if "@@DOCKERFILE@@" in script:
            return workspace_service.ExecResult(0, node_scan, "")
        if "nohup" in script:
            scripts.append(script)
            return workspace_service.ExecResult(0, "QH_STILL_RUNNING\n---QH_LOG---\nok\n", "")
        return workspace_service.ExecResult(0, "", "")

    patches = _patched(runs, projects, exec_fn)

    async def go():
        assert await deploy_pipeline.start_deploy("p13", "u1") is True
        await _await_deploy_settled("p13")

    _with_patches(patches, go)
    # (the wrapper is itself single-quoted inside the script, so the inner quotes appear escaped)
    assert "export PORT=" in scripts[0] and "3000" in scripts[0]
    assert projects.project["deploy_targets"][0]["port"] == 3000


# ---------------------------------------------------------------------------
# The generated start script, executed for real in a local bash (no Sprite needed)
# ---------------------------------------------------------------------------


def test_start_script_in_a_real_shell_reports_crash_exit_code_and_replaces_previous_process():
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
    async def local_exec(project_id, argv, timeout=60, cwd=None):
        script = argv[-1].replace(deploy_pipeline.REPO_ROOT, str(repo))
        r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout)
        return workspace_service.ExecResult(exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr)

    slot = f"qhtest{os.getpid()}"
    pid_file = f"/tmp/qh-deploy-{slot}.pid"
    saved = deploy_pipeline.PROBE_SECONDS
    deploy_pipeline.PROBE_SECONDS = 1
    target_dir = f"{repo}/my dir"

    async def go():
        with mock.patch.object(deploy_pipeline.workspace_service, "exec_in_workspace", local_exec):
            crashed = await deploy_pipeline._start_and_probe("p", target_dir, "echo boom; exit 3", "", slot)
            first = await deploy_pipeline._start_and_probe("p", target_dir, "echo up; sleep 30", "", slot)
            old_pid = open(pid_file).read().strip()
            second = await deploy_pipeline._start_and_probe("p", target_dir, "echo up2; sleep 30", "", slot)
            new_pid = open(pid_file).read().strip()
            return crashed, first, second, old_pid, new_pid

    try:
        crashed, first, second, old_pid, new_pid = _run(go())
    finally:
        deploy_pipeline.PROBE_SECONDS = saved
        subprocess.run(["bash", "-c", f"kill -- -$(cat {pid_file}) 2>/dev/null; rm -f /tmp/qh-deploy-{slot}.*"])
        tmp.cleanup()

    assert crashed == (False, "boom", "", 3)  # a crashed app is reported as crashed, with its real exit code
    assert first[0] is True and second[0] is True
    assert old_pid != new_pid
    assert subprocess.run(["kill", "-0", old_pid], capture_output=True).returncode != 0  # redeploy replaced it
