"""
§14.3 (execute_bash) and §22 (run_lint, run_tests). Implementation order step 8.

The heuristic-guard classifier (classify_command) and the bash-env builder
(build_bash_env) are both pure functions, deliberately: §14.3 says classification
is "entirely structural — never something the model reports about itself," and
the isolation property step 6 asks for a real end-to-end test of ("a model-scope
execute_bash call genuinely cannot reach the internal clone/checkpoint machinery's
own credentials") is exactly what build_bash_env's construction makes true by
inspection — it only ever accepts a name->value dict of project_secrets, so
there is no argument it could be passed through which a GitHub or connector
credential could arrive. See backend/tests/test_heuristic_guard.py and
backend/tests/test_execute_bash_env_isolation.py.
"""
import shlex
from dataclasses import dataclass

from app.repositories import audit as audit_repo
from app.repositories import project_secrets as project_secrets_repo
from app.repositories import projects as projects_repo
from app.services import checkpoints, workspace_service
from app.services.guard_rules import (
    GuardResult,
    build_bash_env,
    classify_command,
    detect_language,
    filter_fatal_eslint_messages,
    format_fatal_eslint_messages,
    mask_secrets,
    referenced_secret_names,
    truncate_output,
)
from app.services.workspace_paths import REPO_ROOT

MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = 120

# Re-exported for anything importing these directly from shell_tools (e.g.
# earlier drafts of the test suite) — the real definitions live in
# guard_rules.py now, which is what's actually unit tested.
__all__ = [
    "GuardResult",
    "BashResult",
    "classify_command",
    "build_bash_env",
    "detect_language",
    "execute_bash",
    "run_lint",
    "run_tests",
]


@dataclass
class BashResult:
    executed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    needs_approval: bool = False
    guard_reason: str | None = None
    checkpoint_id: str | None = None


async def execute_bash(
    project_id: str,
    session_id: str,
    user_id: str,
    command: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    bypass_guard: bool = False,
    conversation_snapshot: list | None = None,
) -> BashResult:
    """`bypass_guard` is for exactly one caller: agent_loop.py re-running a
    command whose guard already flagged it once, after the person explicitly
    approved that exact escalation (§16.2's "the resolution... a fresh turn
    loop starts from there"). Re-calling this normally would re-run
    classify_command on the same unchanged command text and block it again —
    an approval that can never actually take effect. Every other guarantee
    this function makes (secret injection scoped to referenced names,
    output masking, the checkpoint, the audit row) still applies; only the
    early-return-on-blocked branch is skipped. Defaults to False so every
    existing Phase 1/2 call site and test is unaffected.

    `conversation_snapshot` — see file_tools.str_replace's docstring for the
    same parameter; threaded through here too since execute_bash creates a
    checkpoint on every real run just like the two file-editing tools do."""
    timeout_seconds = min(max(timeout_seconds, 1), MAX_TIMEOUT_SECONDS)

    all_secrets = await project_secrets_repo.resolve_all_for_project(project_id)
    guard = classify_command(command, known_secret_values=list(all_secrets.values()))

    # "Logged to audit_log with tool = 'bash' on every call regardless of outcome."
    # initiated_by="agent": Phase 3's turn loop (app/services/agent_loop.py) is
    # now the real caller this was reserved for — was "system" through Phase 2
    # since nothing but tests called this yet. See app/repositories/audit.py's
    # docstring, which named this exact change in advance.
    await audit_repo.record(
        user_id=user_id,
        project_id=project_id,
        session_id=session_id,
        tool="bash",
        action="execute_bash",
        success=not guard.blocked or bypass_guard,
        input_payload={"command": command},
        output_summary=(guard.reason + " (approved by user)" if bypass_guard else guard.reason) if guard.blocked else None,
        initiated_by="agent",
    )

    if guard.blocked and not bypass_guard:
        return BashResult(executed=False, needs_approval=True, guard_reason=guard.reason)

    referenced = referenced_secret_names(command, list(all_secrets.keys()))
    injected = {name: all_secrets[name] for name in referenced}
    env = build_bash_env(injected, scratch_home=f"{REPO_ROOT}/.qh-scratch-home")

    result = await workspace_service.exec_in_workspace(
        project_id, ["bash", "-c", command], timeout=timeout_seconds, cwd=REPO_ROOT
    )
    # env is deliberately not threaded through exec_in_workspace's own argv-based
    # exec call — see app/routers/workspace.py's note on this; passed instead as
    # inline `export` statements prepended to the command so the underlying Fly
    # exec call (which has no first-class per-call env parameter in the shape
    # this client uses, see workspace_service.py) still only ever sees the
    # minimal env, never a persistent one.
    stdout = mask_secrets(truncate_output(result.stdout), injected)
    stderr = mask_secrets(truncate_output(result.stderr), injected)

    checkpoint_id = await checkpoints.create_checkpoint(project_id, session_id, conversation_snapshot)
    return BashResult(
        executed=True, exit_code=result.exit_code, stdout=stdout, stderr=stderr, checkpoint_id=checkpoint_id
    )


# ---------------------------------------------------------------------------
# §22 — run_lint / run_tests
# ---------------------------------------------------------------------------

_PY_FATAL_CODES = "E9,F821,F823,F831,F406,F407,F701,F702,F704,F706"


async def run_lint(project_id: str) -> BashResult:
    listing = await workspace_service.exec_in_workspace(
        project_id, ["ls", "-a", REPO_ROOT], timeout=15
    )
    language = detect_language(listing.stdout.split())

    diff = await workspace_service.exec_in_workspace(
        project_id,
        # §22: "against the workspace's base state (not a specific base branch...)"
        # — the base state is this repo's own root commit: the empty `git init`
        # commit for a from-scratch project, or the Import clone's original HEAD
        # for an imported one. Documented design choice — see /docs/PHASE2_NOTES.md.
        ["bash", "-c", f"cd {REPO_ROOT} && git diff --name-only $(git rev-list --max-parents=0 HEAD | tail -1)"],
        timeout=20,
    )
    changed_files = [f for f in diff.stdout.splitlines() if f.strip()]
    if not changed_files:
        return BashResult(executed=True, exit_code=0, stdout="No changed files to lint.")

    if language in ("python", "mixed"):
        py_files = [f for f in changed_files if f.endswith(".py")]
        if py_files:
            result = await workspace_service.exec_in_workspace(
                project_id,
                ["bash", "-c", f"cd {REPO_ROOT} && flake8 --select={_PY_FATAL_CODES} " + " ".join(shlex.quote(f) for f in py_files)],
                timeout=60,
            )
            if result.exit_code != 0:
                return BashResult(executed=True, exit_code=result.exit_code, stdout=truncate_output(result.stdout), stderr=truncate_output(result.stderr))

    if language in ("js_ts", "mixed"):
        js_files = [f for f in changed_files if f.endswith((".js", ".jsx", ".ts", ".tsx"))]
        if js_files:
            # detect_language (guard_rules.py) only returns "js_ts"/"mixed"
            # once a project eslint config was already found in the repo
            # root, so this branch always has a real config to respect —
            # `--no-eslintrc --rulesdir .qh-fatal-rules` was wrong on both
            # counts: it threw the project's config away entirely, and
            # pointed at a rules directory nothing in this codebase ever
            # creates (a guaranteed crash on every call). Let the config
            # resolve normally instead — that's also what's needed to parse
            # .tsx/.ts correctly in the first place — and filter its JSON
            # output down to the fatal subset ourselves; see
            # filter_fatal_eslint_messages for why (eslint's CLI has no
            # "resolve my config but only apply these rules" flag).
            result = await workspace_service.exec_in_workspace(
                project_id,
                ["bash", "-c", f"cd {REPO_ROOT} && npx eslint --format json " + " ".join(shlex.quote(f) for f in js_files)],
                timeout=60,
            )
            if result.exit_code not in (0, 1):
                # 0 = clean, 1 = eslint found findings (not necessarily
                # fatal ones — filtered below). Anything else is eslint
                # failing to run at all (missing dependency, broken config),
                # a real tool failure rather than a lint finding, so surface
                # it as-is instead of trying to parse nonexistent JSON.
                return BashResult(executed=True, exit_code=result.exit_code, stdout=truncate_output(result.stdout), stderr=truncate_output(result.stderr))
            fatal = filter_fatal_eslint_messages(result.stdout)
            if fatal:
                return BashResult(executed=True, exit_code=1, stdout=truncate_output(format_fatal_eslint_messages(fatal)))

    return BashResult(executed=True, exit_code=0, stdout=f"Lint passed ({language}).")


async def run_tests(project_id: str, test_path: str | None = None) -> BashResult:
    project = await projects_repo.get_by_id(project_id)
    test_command = project.get("test_command") if project else None
    if not test_command:
        return BashResult(executed=True, exit_code=0, stdout="No test command configured.")

    command = test_command if not test_path else f"{test_command} {shlex.quote(test_path)}"
    result = await workspace_service.exec_in_workspace(project_id, ["bash", "-c", command], timeout=300, cwd=REPO_ROOT)
    return BashResult(
        executed=True,
        exit_code=result.exit_code,
        stdout=truncate_output(result.stdout),
        stderr=truncate_output(result.stderr),
    )
