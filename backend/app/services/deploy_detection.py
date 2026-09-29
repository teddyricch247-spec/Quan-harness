"""
§23.5 (stack detection & build) + §23.6 (monorepo root detection) — the pure
decision logic behind both, extracted the same way guard_rules.py/
scheduler_rules.py/tool_partition.py each keep their own rules dependency-free
and directly unit-testable (no app.config/app.db/httpx/workspace_service
import here — see backend/tests/test_deploy_detection.py). app/services/
deploy_pipeline.py is the I/O shell: it runs the actual scan via
workspace_service.exec_in_workspace and the actual LLM fallback call via
llm_client.call_llm, and hands this module already-fetched text to parse.

Two independent detection problems live in this one module because they
share the same two-stage shape (§23.5/§23.6 both describe "a programmatic
pass first, a single tool-less LLM call as fallback when it's ambiguous or
empty"), not because they're the same problem:

  1. `detect_stack` — given one directory's contents, propose
     {stack, build_cmd, run_cmd, port} for that one root. Runs on the from
     -scratch project's single implicit root, and again on every root of a
     confirmed monorepo. Rule-based first (Dockerfile / package.json /
     requirements.txt, Nixpacks' own detection order); the *single* tool-less
     LLM call §23.5 describes is the fallback when none of those rules
     confidently resolve BOTH a build_cmd and a run_cmd — see the module's
     own "all or nothing" note below.
  2. `propose_roots` — given the whole repository's file tree, decide whether
     it's one root or a monorepo, and if the latter, propose named targets.
     Rule-based first (multiple package.json/requirements.txt/Dockerfile at
     different depths, or a turbo.json/nx.json/pnpm-workspace.yaml marker);
     the LLM fallback is only reached when that first pass is ambiguous or
     finds nothing. Deliberately never run for a 'scratch'-origin project —
     see deploy_pipeline.py's own docstring for why that gate lives there,
     not here (it's about *whether* to call propose_roots at all, which is a
     property of the project, not of a file tree this module is handed).

Design decision §23.5's own text doesn't spell out: what happens when a rule
matches the *stack* (e.g. "there's a requirements.txt, so build_cmd is
pip install -r requirements.txt") but can't confidently resolve a *run_cmd*
(no Procfile, no manage.py, no recognizable app.py/main.py entrypoint marker)?
This picks "all or nothing" — detect_stack_from_rules returns None rather than
a half-filled result, and the caller falls through to the LLM fallback for
the *whole* {build_cmd, run_cmd, port} triple, not just the missing piece.
Reasoning: a build_cmd this module is confident about paired with a run_cmd
it had to guess anyway is a worse contract for deploy_pipeline.py's caller
than one clearly-labeled `stack="llm_fallback"` result — "where did this
build plan actually come from" should never be a per-field question.
"""
import json
import re
from dataclasses import dataclass

# Directories no scan ever descends into or reports files under — dependency
# installs, build output, and VCS/scratch state are never a candidate deploy
# root and never worth reporting as one. Kept as a small duplicated literal
# (not an import from repo_map.py) for the same reason guard_rules.py
# duplicates REPO_ROOT rather than importing it: this module stays free of
# any import beyond the standard library, which is what makes it safely
# unit-testable with zero fixtures. Keep in sync with repo_map.py's own
# _EXCLUDED_DIRS by hand if either list changes.
EXCLUDED_DIRS = (".git", ".qh-scratch-home", "node_modules", ".next", "__pycache__", ".venv")

_MONOREPO_MARKER_FILES = ("turbo.json", "nx.json", "pnpm-workspace.yaml")
_ROOT_MARKER_FILES = ("package.json", "requirements.txt", "Dockerfile")

_DEFAULT_NEXT_PORT = 3000
_DEFAULT_PYTHON_PORT = 8000

_PROCFILE_WEB_RE = re.compile(r"^web:\s*(.+)$", re.MULTILINE)
_PACKAGE_JSON_SCRIPT_RE = re.compile(r'"scripts"\s*:\s*\{([^}]*)\}', re.DOTALL)


class DetectionLlmError(ValueError):
    """The tool-less fallback call returned text that isn't the structured
    JSON both detect_stack and propose_roots require. Raised rather than
    silently guessing — see deploy_pipeline.py's own handling: a raised
    DetectionLlmError becomes a clearly-labeled deploy failure ("could not
    determine a build plan"), never a plan built from a partial parse."""


@dataclass
class StackDetectionResult:
    stack: str  # 'nextjs' | 'node' | 'python' | 'dockerfile' | 'llm_fallback'
    build_cmd: str | None
    run_cmd: str | None
    port: int | None


@dataclass
class DeployTargetProposal:
    name: str
    root: str  # relative to the repository root; "." for the single-root case


# ---------------------------------------------------------------------------
# §23.5 — single-root stack detection
# ---------------------------------------------------------------------------


def detect_stack_from_rules(scan: dict) -> StackDetectionResult | None:
    """`scan` is deploy_pipeline.py's already-parsed marker dict for one
    candidate root — see that module's _scan_root docstring for the exact
    keys. Returns None (→ caller falls back to the LLM) when nothing below
    matches confidently, per this module's own "all or nothing" rule.

    Checked in Nixpacks' own stated order (§23.5): Dockerfile first — if
    present, this is the *only* rule that fires, deliberately never combined
    with the package.json/requirements.txt checks below it, since a
    Dockerfile's presence is a declaration of how the repo wants to be built,
    not a fallback signal. Building it is a Live Preview/deploy_pipeline.py
    concern (§23.6's nested-sandboxing rule — Sprites can't do it); detecting
    it is what this function does."""
    if scan.get("dockerfile"):
        return StackDetectionResult(stack="dockerfile", build_cmd=None, run_cmd=None, port=None)

    if scan.get("package_json") is not None:
        result = _detect_node_stack(scan)
        if result is not None:
            return result

    if scan.get("requirements_txt"):
        result = _detect_python_stack(scan)
        if result is not None:
            return result

    return None


def _npm_scripts(package_json_text: str) -> dict[str, str]:
    """A deliberately shallow regex read of just the "scripts" block — not a
    real JSON parse, because a real one would choke on the not-infrequent
    hand-edited package.json with a trailing comma or similar, and all this
    needs is "does a `build`/`start` script exist and what's its value,"
    not a faithful reproduction of npm's own parser."""
    match = _PACKAGE_JSON_SCRIPT_RE.search(package_json_text)
    if not match:
        return {}
    scripts: dict[str, str] = {}
    for line in match.group(1).split(","):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip('"')
        value = value.strip().strip('"')
        if key:
            scripts[key] = value
    return scripts


def _has_next_dependency(package_json_text: str) -> bool:
    return bool(re.search(r'"dependencies"\s*:\s*\{[^}]*"next"\s*:', package_json_text, re.DOTALL))


def _install_cmd(scan: dict) -> str:
    """§23.5 only ever names `next build`/`pip install` — it doesn't say
    which package manager's install command to run first. Picking the wrong
    one for a repo with a pnpm-lock.yaml or yarn.lock (running `npm install`
    against a pnpm-managed tree) is a real, common source of a build that
    fails for reasons that have nothing to do with the app's own code, so
    this is a real decision, not a formality: prefer whichever lockfile is
    actually present, falling back to npm only when none is."""
    if scan.get("pnpm_lock"):
        return "pnpm install"
    if scan.get("yarn_lock"):
        return "yarn install"
    return "npm install"


def _run_script(install: str, script_name: str) -> str:
    """The run-a-script form for whichever package manager _install_cmd
    picked — `npm run build`/`pnpm run build`/`yarn build` all mean the same
    thing, but only yarn drops the literal `run` keyword."""
    if install.startswith("pnpm"):
        return f"pnpm run {script_name}"
    if install.startswith("yarn"):
        return f"yarn {script_name}"
    return f"npm run {script_name}"


def _detect_node_stack(scan: dict) -> StackDetectionResult | None:
    package_json_text = scan["package_json"]
    install = _install_cmd(scan)
    scripts = _npm_scripts(package_json_text)

    if _has_next_dependency(package_json_text):
        build_cmd = f"{install} && {_run_script(install, 'build')}"
        run_cmd = {
            "npm install": "npx next start -p $PORT",
            "pnpm install": "pnpm exec next start -p $PORT",
            "yarn install": "yarn next start -p $PORT",
        }[install]
        return StackDetectionResult(stack="nextjs", build_cmd=build_cmd, run_cmd=run_cmd, port=_DEFAULT_NEXT_PORT)

    # Generic Node: per the module docstring's "all or nothing" rule, this
    # only returns a result when there's a real `start` script to run —
    # a package.json with no start script and no next dependency tells this
    # rule nothing about how to *run* the app, only how to install it, which
    # isn't enough to act on.
    if "start" not in scripts:
        return None
    build_cmd = f"{install} && {_run_script(install, 'build')}" if "build" in scripts else install
    run_cmd = "npm start" if install.startswith("npm") else _run_script(install, "start")
    return StackDetectionResult(stack="node", build_cmd=build_cmd, run_cmd=run_cmd, port=None)


def _detect_python_stack(scan: dict) -> StackDetectionResult | None:
    build_cmd = "pip install -r requirements.txt"

    procfile = scan.get("procfile")
    if procfile:
        match = _PROCFILE_WEB_RE.search(procfile)
        if match:
            return StackDetectionResult(
                stack="python", build_cmd=build_cmd, run_cmd=match.group(1).strip(), port=_DEFAULT_PYTHON_PORT
            )

    if scan.get("manage_py"):
        return StackDetectionResult(
            stack="python",
            build_cmd=build_cmd,
            run_cmd="python manage.py runserver 0.0.0.0:$PORT",
            port=_DEFAULT_PYTHON_PORT,
        )

    for filename, key in (("main.py", "main_py"), ("app.py", "app_py")):
        content = scan.get(key)
        if not content:
            continue
        module = filename[:-3]
        if re.search(r"\bFastAPI\s*\(", content):
            return StackDetectionResult(
                stack="python",
                build_cmd=build_cmd,
                run_cmd=f"uvicorn {module}:app --host 0.0.0.0 --port $PORT",
                port=_DEFAULT_PYTHON_PORT,
            )
        if re.search(r"\bFlask\s*\(", content):
            return StackDetectionResult(
                stack="python",
                build_cmd=build_cmd,
                run_cmd=f"flask --app {module} run --host 0.0.0.0 --port $PORT",
                port=_DEFAULT_PYTHON_PORT,
            )

    # requirements.txt exists but no rule above could confidently name a
    # run_cmd — "all or nothing" (module docstring): fall through to the LLM.
    return None


def build_stack_detection_prompt(root_label: str, scan: dict) -> str:
    """The single tool-less LLM call §23.5 describes for the long tail. Asks
    for strict JSON and nothing else — deploy_pipeline.py passes this
    through llm_client.call_llm with tools=[] (no tool schemas at all, per
    §23.5: "the model never touches a shell or a file directly")."""
    listing = "\n".join(f"- {name}" for name in scan.get("top_level_files", [])) or "(no files found)"
    return (
        "You are proposing a build and run plan for a repository so an automated "
        "pipeline can execute it. You cannot run any command yourself — respond "
        "with ONLY a JSON object, no markdown fences, no other text.\n\n"
        f"Directory: {root_label}\n"
        f"Top-level files in this directory:\n{listing}\n\n"
        "Respond with exactly this shape:\n"
        '{"build_cmd": "<shell command to install dependencies and build, or null '
        'if nothing needs building>", "run_cmd": "<shell command to start the app, '
        'reading its port from the $PORT environment variable>", "port": <integer '
        "port the app will listen on>}"
    )


def parse_stack_detection_response(text: str) -> StackDetectionResult:
    data = parse_json_object(text)
    run_cmd = data.get("run_cmd")
    port = data.get("port")
    if not isinstance(run_cmd, str) or not run_cmd.strip():
        raise DetectionLlmError("LLM stack-detection response is missing a usable run_cmd.")
    if not isinstance(port, int) or isinstance(port, bool) or not (0 < port < 65536):
        raise DetectionLlmError("LLM stack-detection response is missing a valid integer port.")
    build_cmd = data.get("build_cmd")
    if build_cmd is not None and not isinstance(build_cmd, str):
        raise DetectionLlmError("LLM stack-detection response's build_cmd must be a string or null.")
    return StackDetectionResult(stack="llm_fallback", build_cmd=build_cmd, run_cmd=run_cmd, port=port)


# ---------------------------------------------------------------------------
# §23.6 — monorepo root detection (imported repos only — see
# deploy_pipeline.py for the repo_origin gate that decides whether this
# section runs at all)
# ---------------------------------------------------------------------------


def propose_roots_from_markers(marker_paths: list[str]) -> list[DeployTargetProposal] | None:
    """`marker_paths` is every path in the repo (already excluding
    EXCLUDED_DIRS) whose basename is one of _ROOT_MARKER_FILES or
    _MONOREPO_MARKER_FILES — deploy_pipeline.py's scan already filters to
    just these before this function ever runs, so a large repo's full file
    tree never has to cross this boundary just to answer "how many roots
    does this have."

    Returns None (→ caller falls back to the LLM) when this first pass is
    ambiguous or empty, per §23.6's own words. "Ambiguous" here means: a
    monorepo marker file exists (turbo.json etc.) but no matching set of
    per-package root marker files could be paired with real subdirectories —
    i.e., this pass is confident *that* it's a monorepo but not confident
    *where* the roots are, which is exactly the case the LLM fallback (given
    the same file listing plus a "name these roots" prompt) is suited for."""
    root_dirs = sorted({_dirname(p) for p in marker_paths if _basename(p) in _ROOT_MARKER_FILES})
    # A root marker file directly at the repository root (dirname == "")
    # doesn't itself prove single-root — a top-level package.json/
    # requirements.txt commonly coexists with a real monorepo (a workspace
    # root package.json, or a top-level requirements.txt for shared tooling)
    # — so it's excluded from the *count* of real roots below, but kept as a
    # fallback single-root answer if nothing else qualifies.
    non_root_dirs = [d for d in root_dirs if d]
    has_monorepo_marker = any(_basename(p) in _MONOREPO_MARKER_FILES for p in marker_paths)

    if not non_root_dirs and not has_monorepo_marker:
        # No subdirectory has its own package.json/requirements.txt/Dockerfile,
        # and no monorepo tool config either — the ordinary single-root case.
        return [DeployTargetProposal(name="app", root=".")]

    if len(non_root_dirs) >= 2:
        return [DeployTargetProposal(name=_target_name(d), root=d) for d in non_root_dirs]

    # Exactly one non-root dir, or a monorepo marker with zero/one candidate
    # dirs found — both are the "ambiguous" case this pass can't resolve on
    # its own (a monorepo tool config with only one detected package root is
    # more likely a partially-matched scan than a real one-package monorepo).
    if has_monorepo_marker:
        return None

    # Exactly one non-root dir, no monorepo marker at all: a single nested
    # package (e.g. a repo whose actual app lives in a `server/` subfolder
    # with nothing at the true root) is common enough, and unambiguous
    # enough, to resolve here rather than spending an LLM call on it.
    return [DeployTargetProposal(name=_target_name(non_root_dirs[0]), root=non_root_dirs[0])]


def _dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _target_name(root: str) -> str:
    """apps/web -> web; server -> server. Falls back to the full root with
    slashes replaced if the basename alone is empty or unhelpful (shouldn't
    happen given root always comes from a real matched directory, but this
    keeps DeployTargetProposal.name non-empty defensively either way."""
    return _basename(root) or root.replace("/", "-") or "app"


def build_root_proposal_prompt(marker_paths: list[str]) -> str:
    listing = "\n".join(f"- {p}" for p in marker_paths) or "(none found)"
    return (
        "You are identifying the deployable roots of a repository so an automated "
        "pipeline can build and run each one. You cannot run any command yourself — "
        "respond with ONLY a JSON object, no markdown fences, no other text.\n\n"
        "Below are every package.json, requirements.txt, Dockerfile, and monorepo-"
        "tool config file found anywhere in this repository, with their paths "
        f"relative to the repository root:\n{listing}\n\n"
        "Propose one deployable target per independently-buildable part of this "
        "repository (for an ordinary single-project repo, that's exactly one target "
        "with root \".\"). Respond with exactly this shape:\n"
        '{"targets": [{"name": "<short identifier, e.g. \\"frontend\\">", '
        '"root": "<path relative to the repository root, e.g. \\"apps/web\\", or '
        '\\".\\" for the repository root itself>"}]}'
    )


def parse_root_proposal_response(text: str) -> list[DeployTargetProposal]:
    data = parse_json_object(text)
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise DetectionLlmError("LLM root-proposal response has no non-empty 'targets' list.")
    result: list[DeployTargetProposal] = []
    seen_names: set[str] = set()
    for entry in targets:
        if not isinstance(entry, dict):
            raise DetectionLlmError("LLM root-proposal response's targets must be objects.")
        name, root = entry.get("name"), entry.get("root")
        if not isinstance(name, str) or not name.strip() or not isinstance(root, str) or not root.strip():
            raise DetectionLlmError("LLM root-proposal response's targets need non-empty 'name' and 'root' strings.")
        name = name.strip()
        if name in seen_names:
            raise DetectionLlmError(f"LLM root-proposal response used the target name '{name}' more than once.")
        seen_names.add(name)
        result.append(DeployTargetProposal(name=name, root=root.strip()))
    return result


# ---------------------------------------------------------------------------
# Shared JSON parsing — also imported by deploy_diagnosis.py (§23.9), which
# needs the exact same "ask for strict JSON, strip a stray markdown fence,
# raise a clear error on anything else" contract for its own tool-less call.
# Public (no leading underscore) specifically because it's a cross-module
# helper, unlike everything else private in this file.
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict:
    """Strips a markdown code fence if the model wrapped its JSON in one
    despite being asked not to (every provider this codebase's llm_client.py
    can point at does this occasionally) before attempting a real parse."""
    cleaned = _FENCE_RE.sub("", text or "").strip()
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DetectionLlmError(f"LLM response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DetectionLlmError("LLM response's top level must be a JSON object.")
    return data
