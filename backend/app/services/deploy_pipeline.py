"""
§23.5 (stack detection & build), §23.6 (repo structure edge cases), §23.9
(deploy failure handling) — the I/O shell around deploy_detection.py's pure
rules and deploy_diagnosis.py's pure LLM-response parsing. This is the
"deterministic pipeline" §23.5 says "executes that plan" — detection may
involve an LLM call, but nothing here ever hands the model a shell or a file
tool; every actual build/start command runs through
workspace_service.exec_in_workspace the same way shell_tools.execute_bash
does, just without the heuristic guard (there is no agent turn in progress to
guard against here — every command is one this pipeline itself constructed
from a detected or person-confirmed build/run_cmd, not model-issued text).

Same async-background-task-plus-in-memory-pub/sub shape as agent_loop.py's
own start_turn/_subscribers/subscribe/unsubscribe (see that module) — kept
consistent deliberately so routers/deploy.py's SSE stream endpoint
(app/routers/deploy.py) is a near-exact copy of routers/agent.py's
stream_session, not a second pattern to learn. Single-process only, same
caveat as agent_loop.py's own docstring: this doesn't survive a restart or
span multiple backend instances.

One deploy operation at a time *per project* (not per target) — a monorepo's
several targets are all part of the one operation a person started by
clicking Deploy once; deploy_runs_repo.has_running is checked at the project
level, not the target level, and _subscribers below is keyed by project_id
for the same reason.

Design decisions this sub-prompt's own text doesn't spell out, made here and
documented rather than guessed silently — see /docs/PHASE5_1_5_2_5_5_NOTES.md
for the fuller reasoning behind each:

  - "Building a container image regardless of source language" (§23.5) is
    Nixpacks' own general property, cited as the reason Nixpacks' detection
    *order* is worth following — it is not an instruction to build actual
    container images inside a Sprite. Sprites can't do that (§23.6's own
    nested-sandboxing rule says so directly), so a detected Dockerfile is
    handled as an immediate, deterministic §23.6 nested-sandboxing case —
    detected *before* any build is attempted, never attempted and left to
    fail — see _build_and_start's own Dockerfile branch below.
  - A monorepo target literally named "frontend" gets a `BACKEND_URL` env
    var pointing at a same-Sprite "backend" target's own resolved port
    (`http://127.0.0.1:<port>`) once that target is confirmed running — the
    one concrete case §23.6's own example names. This is a narrow, honestly-
    scoped heuristic, not real inter-service dependency detection (out of
    scope for this sub-prompt); a monorepo with different target names, or
    more than two targets, gets no cross-injection.
  - "Start" success is judged by whether the launched process is still alive
    a short probe window later (PROBE_SECONDS), not by an HTTP health check
    against the detected port — many apps don't serve 200 on `/`, and a
    false "unhealthy" from a health-check probe would be a worse failure
    mode than an app that's alive but not yet actually reachable. See
    _start_and_probe's own docstring.
"""
import asyncio
from datetime import datetime, timezone

from app.repositories import deploy_runs as deploy_runs_repo
from app.repositories import projects as projects_repo
from app.services import deploy_detection, deploy_diagnosis, llm_client, workspace_service
from app.services.guard_rules import truncate_output
from app.services.workspace_paths import REPO_ROOT, resolve_repo_path

BUILD_TIMEOUT_SECONDS = 300
START_PROBE_TIMEOUT_SECONDS = 30
PROBE_SECONDS = 5

_NESTED_SANDBOX_MESSAGE = (
    "This app requires nested container support, which preview doesn't support yet. "
    "A Dockerfile was found, but Quan Harness's preview workspaces run on Fly.io Sprites, "
    "which don't support running a Docker build inside them. This isn't something you can "
    "fix from within the app's own code — the app itself is fine."
)

_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe(project_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(project_id, []).append(queue)
    return queue


def unsubscribe(project_id: str, queue: asyncio.Queue) -> None:
    listeners = _subscribers.get(project_id)
    if listeners and queue in listeners:
        listeners.remove(queue)
        if not listeners:
            _subscribers.pop(project_id, None)


def _broadcast(project_id: str, payload: dict) -> None:
    for queue in list(_subscribers.get(project_id, [])):
        queue.put_nowait(payload)


def is_running(project_id: str) -> bool:
    return project_id in _running_projects


_running_projects: set[str] = set()


class DeployNeedsConfirmation(Exception):
    """Raised by start_deploy when an 'imported' project's monorepo roots
    haven't been confirmed yet. Carries the freshly-detected proposal, which
    start_deploy has already persisted (unconfirmed) via
    projects_repo.set_deploy_targets so the confirm UI has something to show
    without a second detection round trip."""

    def __init__(self, proposed_targets: list[dict]):
        self.proposed_targets = proposed_targets
        super().__init__("Deploy targets need to be confirmed before deploying.")


async def start_deploy(project_id: str, user_id: str, force_redetect: bool = False) -> bool:
    """Returns False (no task started) only when a deploy is already running
    for this project — mirrors agent_loop.start_turn's own boolean-return
    "already in progress" contract exactly, for the same 409-vs-202 router
    handling. Raises DeployNeedsConfirmation for an 'imported' project whose
    roots haven't been confirmed (or whose confirmation force_redetect just
    invalidated) — that's a normal, expected flow branch, not an error path,
    which is why it's a distinct exception rather than folded into the
    boolean return."""
    if is_running(project_id) or await deploy_runs_repo.has_running(project_id):
        return False

    project = await projects_repo.get_by_id(project_id)
    targets = project.get("deploy_targets") or []
    confirmed = project.get("deploy_targets_confirmed", False)

    if force_redetect:
        confirmed = False
        targets = []

    if not confirmed:
        if project.get("repo_origin") == "imported":
            proposed = await _detect_roots(project_id)
            proposed_dicts = [_blank_target(t.name, t.root) for t in proposed]
            await projects_repo.set_deploy_targets(project_id, proposed_dicts, confirmed=False)
            raise DeployNeedsConfirmation(proposed_dicts)
        # 'scratch' origin: §23.6 — "there's nothing to detect ... no
        # confirmation prompt is needed." Auto-resolve to the single implicit
        # root and confirm immediately, no person-facing step at all.
        targets = [_blank_target("app", ".")]
        await projects_repo.set_deploy_targets(project_id, targets, confirmed=True)

    _running_projects.add(project_id)
    asyncio.create_task(_run_deploy(project_id, user_id, targets))
    return True


async def confirm_targets(project_id: str, targets: list[dict]) -> list[dict]:
    """§23.6: "The person confirms once; saved as projects.deploy_targets
    from then on." Re-callable at any time to edit an already-confirmed
    shape (add/remove/rename a target) — always re-blanks build_cmd/run_cmd/
    port/stack, since a changed root or a newly-added target has nothing
    valid to keep from before, and keeping a stale build plan for an
    unchanged target silently would be a worse default than re-detecting it
    once on the next deploy (§23.5's rule-based path is cheap; the LLM
    fallback only fires when it has to)."""
    blanked = [_blank_target(t["name"], t["root"]) for t in targets]
    await projects_repo.set_deploy_targets(project_id, blanked, confirmed=True)
    return blanked


def _blank_target(name: str, root: str) -> dict:
    return {"name": name, "root": root, "stack": None, "build_cmd": None, "run_cmd": None, "port": None}


async def _detect_roots(project_id: str) -> list[deploy_detection.DeployTargetProposal]:
    scan = await workspace_service.exec_in_workspace(
        project_id, ["bash", "-c", _ROOT_MARKER_SCAN_SCRIPT], timeout=30, cwd=REPO_ROOT
    )
    marker_paths = [line for line in scan.stdout.splitlines() if line.strip()]
    proposal = deploy_detection.propose_roots_from_markers(marker_paths)
    if proposal is not None:
        return proposal

    project = await projects_repo.get_by_id(project_id)
    credential = await llm_client.resolve_credential(project)
    prompt = deploy_detection.build_root_proposal_prompt(marker_paths)
    response = await llm_client.call_llm([{"role": "user", "content": prompt}], tools=[], credential=credential)
    return deploy_detection.parse_root_proposal_response(response.text)


_ROOT_MARKER_SCAN_SCRIPT = (
    r"find . \( -name '.git' -o -name 'node_modules' -o -name '.next' -o -name '__pycache__' "
    r"-o -name '.venv' -o -name '.qh-scratch-home' \) -prune -o -type f "
    r"\( -name 'package.json' -o -name 'requirements.txt' -o -name 'Dockerfile' "
    r"-o -name 'turbo.json' -o -name 'nx.json' -o -name 'pnpm-workspace.yaml' \) -print "
    r"| sed 's#^\./##'; true"
)


# ---------------------------------------------------------------------------
# The actual multi-target run
# ---------------------------------------------------------------------------


async def _run_deploy(project_id: str, user_id: str, targets: list[dict]) -> None:
    try:
        project = await projects_repo.get_by_id(project_id)
        ordered = _order_targets(targets)
        resolved_ports: dict[str, int] = {}
        overall_ok = True

        for target in ordered:
            extra_env = {}
            if target["name"].strip().lower() == "frontend" and "backend" in resolved_ports:
                extra_env["BACKEND_URL"] = f"http://127.0.0.1:{resolved_ports['backend']}"
            ok, resolved_target = await _deploy_one_target(project, user_id, target, extra_env)
            overall_ok = overall_ok and ok
            if ok and resolved_target.get("port"):
                resolved_ports[target["name"].strip().lower()] = resolved_target["port"]
            # Persist whatever detection resolved (stack/build_cmd/run_cmd/
            # port), win or lose — a failed *start* still means the build's
            # own detected plan was correct and shouldn't be thrown away and
            # re-detected (possibly differently, if it's an LLM fallback
            # result) on the very next attempt.
            targets = [resolved_target if t["name"] == target["name"] else t for t in targets]
            await projects_repo.set_deploy_targets(project_id, targets, confirmed=True)

        _broadcast(project_id, {"type": "__deploy_status__", "status": "completed" if overall_ok else "failed"})
    finally:
        _running_projects.discard(project_id)


def _order_targets(targets: list[dict]) -> list[dict]:
    """A target literally named "backend" goes first when both it and one
    literally named "frontend" are present, so the frontend's BACKEND_URL
    injection (module docstring) has a resolved port to use by the time it's
    that target's own turn. Every other ordering is left as declared —
    there's no general dependency graph here (module docstring)."""
    names = {t["name"].strip().lower() for t in targets}
    if "backend" in names and "frontend" in names:
        return sorted(targets, key=lambda t: 0 if t["name"].strip().lower() == "backend" else 1)
    return targets


async def _deploy_one_target(project: dict, user_id: str, target: dict, extra_env: dict) -> tuple[bool, dict]:
    project_id = project["id"]
    target_name = target["name"] if target["root"] != "." or len(project.get("deploy_targets") or []) > 1 else None

    run_row = await deploy_runs_repo.create(
        project_id,
        {"target_name": target_name, "status": "running", "phase": "detect"},
    )
    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "detect", "status": "running"})

    scan = await _scan_root(project_id, target["root"])

    if scan.get("dockerfile"):
        await deploy_runs_repo.update(
            run_row["id"],
            {
                "status": "failed",
                "phase": "build",
                "stack": "dockerfile",
                "failure_class": "environment",
                "diagnosis_text": _NESTED_SANDBOX_MESSAGE,
                "completed_at": _now_iso(),
            },
        )
        _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "failed", "nested_sandbox": True})
        return False, {**target, "stack": "dockerfile"}

    try:
        detection = await _resolve_stack(project, target, scan)
    except (deploy_detection.DetectionLlmError, llm_client.NoLlmCredentialError, llm_client.LlmCallFailedError) as exc:
        await deploy_runs_repo.update(
            run_row["id"],
            {
                "status": "failed",
                "phase": "detect",
                "stderr": truncate_output(str(exc)),
                "failure_class": "environment",
                "diagnosis_text": f"Couldn't determine how to build or run this project: {exc}",
                "completed_at": _now_iso(),
            },
        )
        _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "detect", "status": "failed"})
        return False, target

    resolved_target = {
        "name": target["name"],
        "root": target["root"],
        "stack": detection.stack,
        "build_cmd": detection.build_cmd,
        "run_cmd": detection.run_cmd,
        "port": detection.port,
    }
    await deploy_runs_repo.update(run_row["id"], {"stack": detection.stack, "build_cmd": detection.build_cmd, "run_cmd": detection.run_cmd, "port": detection.port})

    cwd = resolve_repo_path(target["root"])
    port = detection.port
    env_prefix = _env_prefix({**({"PORT": str(port)} if port else {}), **extra_env})

    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "running"})
    if detection.build_cmd:
        build_result = await workspace_service.exec_in_workspace(
            project_id, ["bash", "-c", f"{env_prefix}{detection.build_cmd}"], timeout=BUILD_TIMEOUT_SECONDS, cwd=cwd
        )
        stdout, stderr = truncate_output(build_result.stdout), truncate_output(build_result.stderr)
        if build_result.exit_code != 0:
            await _fail_run(project, run_row["id"], "build", detection.build_cmd, None, stdout, stderr, build_result.exit_code)
            _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "failed"})
            return False, resolved_target
        await deploy_runs_repo.update(run_row["id"], {"stdout": stdout, "stderr": stderr})

    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "start", "status": "running"})
    started, run_stdout, run_stderr, exit_code = await _start_and_probe(project_id, cwd, detection.run_cmd, env_prefix, run_row["id"])
    if not started:
        await _fail_run(project, run_row["id"], "start", detection.build_cmd, detection.run_cmd, run_stdout, run_stderr, exit_code)
        _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "start", "status": "failed"})
        return False, resolved_target

    await deploy_runs_repo.update(
        run_row["id"], {"status": "success", "phase": "healthy", "stdout": run_stdout, "stderr": run_stderr, "completed_at": _now_iso()}
    )
    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "healthy", "status": "success"})
    return True, resolved_target


async def _resolve_stack(project: dict, target: dict, scan: dict) -> deploy_detection.StackDetectionResult:
    if target.get("build_cmd") or target.get("run_cmd"):
        # Already resolved on a previous deploy (module docstring: "a failed
        # start still means the build's own detected plan was correct").
        return deploy_detection.StackDetectionResult(
            stack=target.get("stack") or "llm_fallback", build_cmd=target.get("build_cmd"), run_cmd=target.get("run_cmd"), port=target.get("port")
        )
    rule_result = deploy_detection.detect_stack_from_rules(scan)
    if rule_result is not None:
        return rule_result
    credential = await llm_client.resolve_credential(project)
    prompt = deploy_detection.build_stack_detection_prompt(target["root"], scan)
    response = await llm_client.call_llm([{"role": "user", "content": prompt}], tools=[], credential=credential)
    return deploy_detection.parse_stack_detection_response(response.text)


async def _fail_run(project: dict, run_id: str, phase: str, build_cmd, run_cmd, stdout: str, stderr: str, exit_code) -> None:
    """§23.9 point 1 (raw log, already true by the time this is called — the
    caller already wrote stdout/stderr/exit_code) then point 2 (a best-effort
    diagnosis on top of it — see deploy_diagnosis.py's own docstring for why
    a failed diagnosis call must never block this from marking the run
    failed with what it already has)."""
    fields: dict = {"status": "failed", "phase": phase, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "completed_at": _now_iso()}
    try:
        credential = await llm_client.resolve_credential(project)
        diagnosis = await deploy_diagnosis.diagnose(phase, build_cmd, run_cmd, stdout, stderr, exit_code, credential)
        fields["failure_class"] = diagnosis.failure_class
        fields["diagnosis_text"] = diagnosis.diagnosis_text
        fields["suggested_fix_prompt"] = diagnosis.suggested_fix_prompt
    except (llm_client.NoLlmCredentialError, llm_client.LlmCallFailedError, deploy_diagnosis.DiagnosisLlmError):
        pass  # best-effort — the raw log above is already saved regardless
    await deploy_runs_repo.update(run_id, fields)


# ---------------------------------------------------------------------------
# Scanning and process start/probe
# ---------------------------------------------------------------------------

_ROOT_SCAN_SCRIPT = (
    "[ -f Dockerfile ] && echo '@@DOCKERFILE@@'; "
    "[ -f package.json ] && { echo '@@PACKAGE_JSON@@'; cat package.json; }; "
    "[ -f requirements.txt ] && echo '@@REQUIREMENTS_TXT@@'; "
    "[ -f Procfile ] && { echo '@@PROCFILE@@'; cat Procfile; }; "
    "[ -f manage.py ] && echo '@@MANAGE_PY@@'; "
    "[ -f app.py ] && { echo '@@APP_PY@@'; cat app.py; }; "
    "[ -f main.py ] && { echo '@@MAIN_PY@@'; cat main.py; }; "
    "[ -f pnpm-lock.yaml ] && echo '@@PNPM_LOCK@@'; "
    "[ -f yarn.lock ] && echo '@@YARN_LOCK@@'; "
    "echo '@@TOP_LEVEL_FILES@@'; "
    "ls -1a . 2>/dev/null | grep -v -E '^(\\.|\\.\\.|\\.git|node_modules|\\.next|__pycache__|\\.venv)$'; "
    "true"
)

_SCAN_SECTION_KEYS = {
    "@@DOCKERFILE@@": ("dockerfile", "flag"),
    "@@PACKAGE_JSON@@": ("package_json", "text"),
    "@@REQUIREMENTS_TXT@@": ("requirements_txt", "flag"),
    "@@PROCFILE@@": ("procfile", "text"),
    "@@MANAGE_PY@@": ("manage_py", "flag"),
    "@@APP_PY@@": ("app_py", "text"),
    "@@MAIN_PY@@": ("main_py", "text"),
    "@@PNPM_LOCK@@": ("pnpm_lock", "flag"),
    "@@YARN_LOCK@@": ("yarn_lock", "flag"),
    "@@TOP_LEVEL_FILES@@": ("top_level_files", "list"),
}


async def _scan_root(project_id: str, root: str) -> dict:
    cwd = resolve_repo_path(root)
    result = await workspace_service.exec_in_workspace(project_id, ["bash", "-c", _ROOT_SCAN_SCRIPT], timeout=30, cwd=cwd)
    return _parse_root_scan(result.stdout)


def _parse_root_scan(raw: str) -> dict:
    scan: dict = {}
    current_key: str | None = None
    current_kind: str | None = None
    buffer: list[str] = []

    def _flush():
        if current_key is None:
            return
        if current_kind == "flag":
            scan[current_key] = True
        elif current_kind == "text":
            scan[current_key] = "\n".join(buffer)
        elif current_kind == "list":
            scan[current_key] = [line for line in buffer if line.strip()]

    for line in raw.splitlines():
        if line in _SCAN_SECTION_KEYS:
            _flush()
            current_key, current_kind = _SCAN_SECTION_KEYS[line]
            buffer = []
            if current_kind == "flag":
                scan[current_key] = True
            continue
        if current_key is not None:
            buffer.append(line)
    _flush()
    return scan


def _env_prefix(env: dict[str, str]) -> str:
    """Same technique shell_tools.execute_bash uses for project secrets —
    inline `export` statements prepended to the command text, since
    exec_in_workspace/the underlying Sprites exec call has no first-class
    per-call env parameter (see workspace_service.py's own docstring)."""
    if not env:
        return ""
    exports = " && ".join(f"export {name}={_shell_quote(value)}" for name, value in env.items())
    return f"{exports} && "


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


async def _start_and_probe(project_id: str, target_dir: str, run_cmd: str, env_prefix: str, run_id: str) -> tuple[bool, str, str, int | None]:
    """Launches run_cmd detached (nohup, backgrounded, disowned from the
    shell exec_in_workspace itself runs), waits PROBE_SECONDS, then checks
    whether the process is still alive. "Still alive after a few seconds" —
    not an HTTP health check against the detected port — is the health
    signal (module docstring): a process that's still running is evidence
    the app didn't crash on startup (a missing dependency, a bad config
    read, a syntax error the build step's own language didn't catch), which
    is what this phase exists to catch; whether it's *also* correctly
    serving HTTP yet is a separate, later concern (§23's Live Preview /
    proxying, out of scope here).

    One exec_in_workspace call does the launch, the sleep, the aliveness
    check, and the log tail together — same "one round trip" cost-
    consciousness as run_lint/repo_map's own combined scripts. The exec
    call's own `cwd` is REPO_ROOT regardless of `target_dir` — the script
    does its own `cd` into target_dir before launching, so the top-level
    exec cwd is just a neutral starting point."""
    log_path = f"/tmp/qh-deploy-{run_id}.log"
    pid_path = f"/tmp/qh-deploy-{run_id}.pid"
    script = (
        f"cd {target_dir} && "
        f"({env_prefix}nohup bash -c {_shell_quote(run_cmd)} > {log_path} 2>&1 & echo $! > {pid_path}) ; "
        f"sleep {PROBE_SECONDS} ; "
        f"if kill -0 $(cat {pid_path}) 2>/dev/null; then "
        f'  echo "QH_STILL_RUNNING"; '
        f"else "
        f'  wait $(cat {pid_path}) 2>/dev/null; echo "QH_EXIT_CODE:$?"; '
        f"fi; "
        f"echo '---QH_LOG---'; cat {log_path} 2>/dev/null"
    )
    result = await workspace_service.exec_in_workspace(
        project_id, ["bash", "-c", script], timeout=START_PROBE_TIMEOUT_SECONDS, cwd=REPO_ROOT
    )
    stdout = result.stdout
    still_running = "QH_STILL_RUNNING" in stdout.splitlines()[:3] if stdout else False
    log_tail = stdout.split("---QH_LOG---", 1)[-1].strip() if "---QH_LOG---" in stdout else stdout

    if still_running:
        return True, truncate_output(log_tail), truncate_output(result.stderr), None

    exit_code = None
    for line in stdout.splitlines():
        if line.startswith("QH_EXIT_CODE:"):
            try:
                exit_code = int(line.split(":", 1)[1])
            except ValueError:
                exit_code = None
            break
    return False, truncate_output(log_tail), truncate_output(result.stderr), exit_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
