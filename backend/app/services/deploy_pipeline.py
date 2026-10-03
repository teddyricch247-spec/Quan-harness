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
    nested-sandboxing rule says so directly). §23.6 is specific about WHAT is
    unsupported: "if the repo's own logic tries to spin up its own Docker/
    sandbox inside the workspace's Sprite" — i.e. a build or start command that
    invokes Docker. A Dockerfile merely *existing* in a repository is not that,
    and Phase 5.1 originally treated it as that (any Dockerfile → immediate
    nested-sandbox failure), which refused to preview every repo that ships
    one for production use. Corrected in Phase 5.3/5.4: a Dockerfile is ignored
    by detection, and nested-container support is declared only when the
    detected/confirmed build or run command actually invokes docker/podman, or
    when a log shows the Docker daemon being unavailable — see
    preview_limitations.mentions_docker / classify_environment_issue.
  - Phase 5.3: the app is started as a Sprite SERVICE, not a detached `nohup`
    process — a Sprite's RAM doesn't persist across hibernation, so a `nohup`ed
    app dies ~30s after the deploy that started it. See preview_runtime.py's
    module docstring for the full reasoning, and for how preview secrets reach the
    app (through the service's env only).
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
import logging
from datetime import datetime, timezone

from app.repositories import deploy_runs as deploy_runs_repo
from app.repositories import projects as projects_repo
from app.services import (
    deploy_detection,
    deploy_diagnosis,
    llm_client,
    preview_limitations,
    preview_notifications,
    preview_runtime,
    preview_secrets_service,
    workspace_service,
)
from app.services.guard_rules import truncate_output
from app.services.workspace_paths import REPO_ROOT, resolve_repo_path

logger = logging.getLogger(__name__)

BUILD_TIMEOUT_SECONDS = 300
START_PROBE_TIMEOUT_SECONDS = 30
PROBE_SECONDS = 5

_NESTED_SANDBOX_MESSAGE = (
    "This app requires nested container support, which preview doesn't support yet. "
    "Its own build or start-up needs Docker, but Quan Harness's preview workspaces run on "
    "Fly.io Sprites, which can't run containers inside them. This isn't something you can "
    "fix from within the app's own code — the app itself is fine. (A Dockerfile that merely "
    "exists in the repository isn't the problem; only a command that actually invokes Docker is.)"
)

_ORPHANED_RUN_MESSAGE = (
    "This deploy was interrupted before it finished (the backend restarted or hit an unexpected error)."
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
    if is_running(project_id):
        return False
    # Claim the slot before the first await: two near-simultaneous requests
    # (a double click) used to both pass the check above and both start a
    # deploy, because the set was only added to after several awaits.
    _running_projects.add(project_id)
    launched = False
    try:
        # This backend is single-process (module docstring), so the in-memory
        # set above is the source of truth for "is a deploy running". A row
        # still marked 'running' in the database while nothing is running here
        # was orphaned by a restart or an unhandled error — close it out now,
        # otherwise it would block every future deploy of this project.
        await deploy_runs_repo.fail_orphaned_running(project_id, _ORPHANED_RUN_MESSAGE)

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

        asyncio.create_task(_run_deploy(project_id, user_id, targets))
        launched = True
        return True
    finally:
        if not launched:
            _running_projects.discard(project_id)


async def confirm_targets(project_id: str, targets: list[dict]) -> list[dict]:
    """§23.6: "The person confirms once; saved as projects.deploy_targets
    from then on." Re-callable at any time to edit an already-confirmed
    shape (add/remove/rename a target) — always re-blanks build_cmd/run_cmd/
    port/stack, since a changed root or a newly-added target has nothing
    valid to keep from before, and keeping a stale build plan for an
    unchanged target silently would be a worse default than re-detecting it
    once on the next deploy (§23.5's rule-based path is cheap; the LLM
    fallback only fires when it has to)."""
    blanked = [_blank_target(t["name"].strip(), t["root"].strip()) for t in targets]
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
        # Phase 5.3: a Sprite's URL routes to ONE port, so exactly one target — the
        # entry target (a frontend, else the first non-backend) — is given the
        # `http_port` that the preview points at. See preview_runtime.entry_target_name.
        entry_name = preview_runtime.entry_target_name(targets)
        resolved_ports: dict[str, int] = {}
        overall_ok = True

        for target in ordered:
            extra_env = {}
            if target["name"].strip().lower() == "frontend" and "backend" in resolved_ports:
                extra_env["BACKEND_URL"] = f"http://127.0.0.1:{resolved_ports['backend']}"
            ok, resolved_target = await _deploy_one_target(project, user_id, target, extra_env, entry_name=entry_name)
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

        if overall_ok:
            # §23.9 point 4 / §23.8: a deploy that worked closes the notifications a
            # failed one raised (a green deploy says nothing about runtime-only
            # problems like CORS, which is why only deploy-failure ones are closed).
            await preview_notifications.resolve_after_success(project_id)
        _broadcast(project_id, {"type": "__deploy_status__", "status": "completed" if overall_ok else "failed"})
    except Exception as exc:  # noqa: BLE001 — anything unexpected must still close out the run row
        logger.exception("Deploy pipeline crashed for project %s", project_id)
        try:
            await deploy_runs_repo.fail_orphaned_running(project_id, f"Deploy pipeline error: {exc}")
        except Exception:  # noqa: BLE001
            logger.exception("Could not mark the crashed deploy run as failed for project %s", project_id)
        _broadcast(project_id, {"type": "__deploy_status__", "status": "failed"})
    finally:
        _running_projects.discard(project_id)


def _order_targets(targets: list[dict]) -> list[dict]:
    """Moved to preview_runtime.order_targets in Phase 5.3 (preview_runtime.restart_all
    needs the identical ordering and can't import this module without a cycle)."""
    return preview_runtime.order_targets(targets)


async def _redact(project_id: str, text: str | None) -> str:
    """§23.10: a preview secret's value never lands in a stored log, a diagnosis,
    or anything the model later reads. Build/start output is all three."""
    return (await preview_secrets_service.redact_text(project_id, text)) or ""


async def _deploy_one_target(
    project: dict, user_id: str, target: dict, extra_env: dict, entry_name: str | None = None
) -> tuple[bool, dict]:
    project_id = project["id"]
    target_name = target["name"] if target["root"] != "." or len(project.get("deploy_targets") or []) > 1 else None

    run_row = await deploy_runs_repo.create(
        project_id,
        {"target_name": target_name, "status": "running", "phase": "detect"},
    )
    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "detect", "status": "running"})

    scan = await _scan_root(project_id, target["root"])

    # §23.8's secrets row, caught BEFORE the app fails: if the repo ships a
    # .env.example naming variables the preview hasn't been given, say so now.
    # Informational and non-blocking — the deploy proceeds either way.
    await preview_notifications.scan_missing_env(project_id, scan.get("env_example"), run_row["id"])

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

    await deploy_runs_repo.update(run_row["id"], {"stack": detection.stack, "build_cmd": detection.build_cmd, "run_cmd": detection.run_cmd, "port": detection.port})

    # §23.6: "if the repo's own logic tries to spin up its own Docker/sandbox" —
    # detected deterministically from the commands themselves, before anything is
    # attempted. Deliberately NOT triggered by a Dockerfile merely existing (see the
    # module docstring). The unresolved `target` is returned, not a resolved one: the
    # commands that need Docker must not be persisted as "the plan", or every later
    # deploy would reuse them instead of re-detecting after the person changes the repo.
    if preview_limitations.mentions_docker(detection.build_cmd) or preview_limitations.mentions_docker(detection.run_cmd):
        await deploy_runs_repo.update(run_row["id"], {"status": "failed", "phase": "build", "completed_at": _now_iso()})
        await _record_environment_failure(project_id, run_row["id"], "nested_container", _NESTED_SANDBOX_MESSAGE)
        _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "failed", "nested_sandbox": True})
        return False, target

    resolved_target = {
        "name": target["name"],
        "root": target["root"],
        "stack": detection.stack,
        "build_cmd": detection.build_cmd,
        "run_cmd": detection.run_cmd,
        "port": detection.port,
    }

    cwd = resolve_repo_path(target["root"])
    port = detection.port
    # The BUILD step gets only harness-managed variables — preview secrets are
    # runtime-only (§23.8: "injected into the Sprite's runtime env only"), and this
    # string ends up in a command line.
    env_prefix = _env_prefix({**({"PORT": str(port)} if port else {}), **extra_env})

    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "running"})
    if detection.build_cmd:
        build_result = await workspace_service.exec_in_workspace(
            project_id, ["bash", "-c", f"{env_prefix}{detection.build_cmd}"], timeout=BUILD_TIMEOUT_SECONDS, cwd=cwd
        )
        stdout = await _redact(project_id, truncate_output(build_result.stdout))
        stderr = await _redact(project_id, truncate_output(build_result.stderr))
        if build_result.exit_code != 0:
            await _fail_run(project, run_row["id"], "build", detection.build_cmd, None, stdout, stderr, build_result.exit_code)
            _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "build", "status": "failed"})
            return False, resolved_target
        await deploy_runs_repo.update(run_row["id"], {"stdout": stdout, "stderr": stderr})

    _broadcast(project_id, {"type": "phase", "run_id": run_row["id"], "target_name": target_name, "phase": "start", "status": "running"})
    # The RUNTIME env: the person's preview secrets (fetched fresh from Vault) with
    # the harness-managed variables on top. Goes to the Sprite service's `env`
    # parameter — never into a command line, never into a file this harness writes.
    secret_env = await preview_secrets_service.get_runtime_env(project_id)
    run_env = preview_runtime.build_target_env(port, extra_env, secret_env)
    http_port = port if (entry_name is not None and target["name"] == entry_name and port) else None
    started, run_stdout, run_stderr, exit_code = await _start_and_probe(
        project_id, cwd, detection.run_cmd, run_env, target["name"], http_port=http_port
    )
    run_stdout, run_stderr = await _redact(project_id, run_stdout), await _redact(project_id, run_stderr)
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
    """§23.9 point 1 then point 2, in that order and as two separate writes:
    the raw stdout/stderr/exit_code is saved (and the run marked failed) FIRST,
    so the Console tab shows it immediately; the tool-less diagnosis call
    happens afterwards and lands on the same row when it finishes. Writing
    both in one update after the LLM call — as this used to — meant the raw log
    stayed invisible for as long as the diagnosis took, and was lost with it if
    that call raised something unexpected. See deploy_diagnosis.py's own
    docstring for why a failed diagnosis must never take the raw log with it.

    Phase 5.4 adds §23.9 point 4's routing: an *environment* failure (not a bug in
    the app's code) is classified into one of §23.8's known limitations and
    raised as a notification. A Docker-daemon failure is recognised
    deterministically and never costs an LLM call; everything else uses the
    diagnosis model's `environment_kind`, with the same pure classifier as the
    fallback when no model is available."""
    project_id = project["id"]
    stdout, stderr = await _redact(project_id, stdout), await _redact(project_id, stderr)
    await deploy_runs_repo.update(
        run_id,
        {"status": "failed", "phase": phase, "exit_code": exit_code, "stdout": stdout, "stderr": stderr, "completed_at": _now_iso()},
    )
    heuristic_kind = preview_limitations.classify_environment_issue(f"{stdout}\n{stderr}")

    if heuristic_kind == "nested_container":
        await _record_environment_failure(project_id, run_id, "nested_container", _NESTED_SANDBOX_MESSAGE)
        return

    try:
        credential = await llm_client.resolve_credential(project)
        diagnosis = await deploy_diagnosis.diagnose(phase, build_cmd, run_cmd, stdout, stderr, exit_code, credential)
        kind = (diagnosis.environment_kind or heuristic_kind or "other") if diagnosis.failure_class == "environment" else None
        diagnosis_text = await _redact(project_id, diagnosis.diagnosis_text)
        await deploy_runs_repo.update(
            run_id,
            {
                "failure_class": diagnosis.failure_class,
                "environment_kind": kind,
                "diagnosis_text": diagnosis_text,
                "suggested_fix_prompt": diagnosis.suggested_fix_prompt,
            },
        )
        if kind:
            await preview_notifications.raise_environment_failure(project_id, kind, diagnosis_text, run_id)
    except (llm_client.NoLlmCredentialError, llm_client.LlmCallFailedError, deploy_diagnosis.DiagnosisLlmError):
        # No model to ask — but a recognisable environment signature in the log is
        # still worth surfacing, so the person isn't left with only a raw log.
        if heuristic_kind:
            await _record_environment_failure(project_id, run_id, heuristic_kind, None)
    except Exception:  # noqa: BLE001 — diagnosis is never allowed to fail the deploy itself
        logger.exception("Deploy diagnosis crashed for run %s", run_id)


async def _record_environment_failure(project_id: str, run_id: str, kind: str, text: str | None) -> None:
    """Marks a run as an environment failure of a known §23.8 kind and raises the
    matching notification. With no `text`, the standing guidance for that kind is
    used as the diagnosis, so the Deploy panel and the notification agree."""
    if text is None:
        ctx = await preview_notifications.context_for(project_id)
        text = preview_limitations.guidance_for(kind, ctx)["why"]
    await deploy_runs_repo.update(
        run_id,
        {"failure_class": "environment", "environment_kind": kind, "diagnosis_text": text, "suggested_fix_prompt": None},
    )
    await preview_notifications.raise_environment_failure(project_id, kind, text, run_id)


# ---------------------------------------------------------------------------
# Scanning and process start/probe
# ---------------------------------------------------------------------------

# Every `cat` below is followed by `echo`: a file with no trailing newline (very common
# for hand-edited or tool-generated package.json/Procfile) would otherwise have the
# NEXT section marker glued onto its last line, and _parse_root_scan would never see
# that marker — silently losing the following section (for package.json that meant
# losing @@PNPM_LOCK@@/@@YARN_LOCK@@ and @@TOP_LEVEL_FILES@@, so a pnpm project
# was built with npm). Found in Phase 5.3's review of the .env.example capture.
_ROOT_SCAN_SCRIPT = (
    "[ -f Dockerfile ] && echo '@@DOCKERFILE@@'; "
    "[ -f package.json ] && { echo '@@PACKAGE_JSON@@'; cat package.json; echo; }; "
    "[ -f requirements.txt ] && echo '@@REQUIREMENTS_TXT@@'; "
    "[ -f Procfile ] && { echo '@@PROCFILE@@'; cat Procfile; echo; }; "
    "[ -f manage.py ] && echo '@@MANAGE_PY@@'; "
    "[ -f app.py ] && { echo '@@APP_PY@@'; cat app.py; echo; }; "
    "[ -f main.py ] && { echo '@@MAIN_PY@@'; cat main.py; echo; }; "
    "[ -f pnpm-lock.yaml ] && echo '@@PNPM_LOCK@@'; "
    "[ -f yarn.lock ] && echo '@@YARN_LOCK@@'; "
    # Phase 5.4: the first .env.example-style file, capped. The trailing `echo` matters:
    # `head -c` can stop mid-line with no newline, and without it the next section
    # marker would be glued onto the end of the last variable and never recognised.
    "for f in .env.example .env.sample .env.template .env.local.example; do "
    "[ -f \"$f\" ] && { echo '@@ENV_EXAMPLE@@'; head -c 20000 \"$f\"; echo; break; }; done; "
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
    "@@ENV_EXAMPLE@@": ("env_example", "text"),
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


_shell_quote = preview_runtime.shell_quote
_slot_slug = preview_runtime.slot_slug


async def _start_and_probe(
    project_id: str,
    target_dir: str,
    run_cmd: str,
    env: dict[str, str],
    target_name: str,
    http_port: int | None = None,
) -> tuple[bool, str, str, int | None]:
    """Starts run_cmd as a Sprite service and judges it by whether it is still alive
    PROBE_SECONDS later. The mechanics live in preview_runtime.launch_and_probe —
    this wrapper keeps the name and the (started, log, stderr, exit_code) contract
    this module's callers and tests have used since 5.1.

    The health signal is unchanged from 5.1 and still deliberately NOT an HTTP
    check (module docstring): "still alive after a few seconds" catches an app that
    crashed on startup (missing dependency, bad config read, a syntax error the
    build step didn't catch), without a false "unhealthy" for the many apps that
    don't answer 200 on `/`.

    What changed in 5.3 is only WHO runs the process — a Sprite service instead of a
    detached `nohup` that died with the Sprite's RAM (preview_runtime's module
    docstring) — and that `env` is now a dict handed to the service, not a string of
    `export` statements baked into a command line. That second change is what lets
    preview secrets reach the app without ever appearing in an argv."""
    return await preview_runtime.launch_and_probe(
        project_id, target_dir, run_cmd, env, target_name, http_port=http_port, probe_seconds=PROBE_SECONDS
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
