#!/usr/bin/env python3
"""
Quan-harness fixes. Run from the ROOT of the repo (the folder that contains backend/):

    python apply_fix.py

Edits three files in place:
  backend/app/services/agent_loop.py     view_range crash + a raising tool no longer kills the session
  backend/app/services/deploy_detection.py   plain index.html sites get a rule-based start command
  backend/app/services/system_prompt.py  a short PREVIEW_RULES block so the agent knows the preview's limits

Each file is applied independently and all-or-nothing: if a REQUIRED expected text isn't found exactly once in a
file, that file is left untouched (the others still apply) and the script exits with status 1. Safe to run twice.
"""
import ast
import sys
from pathlib import Path

AGENT_LOOP = "backend/app/services/agent_loop.py"
DETECTION = "backend/app/services/deploy_detection.py"
PROMPT = "backend/app/services/system_prompt.py"

# (label, file, old text, new text, required)
EDITS = [
    (
        "1. agent_loop._as_range: stop calling len() on a non-sequence view_range",
        AGENT_LOOP,
        '''def _as_range(value) -> tuple[int, int] | None:
    if not value or len(value) != 2:
        return None
''',
        '''def _as_range(value) -> tuple[int, int] | None:
    # `view_range` comes straight from the model's JSON tool call, and some models send a bare number or a
    # string instead of [start, end]. `len(50)` raised "object of type 'int' has no len()" out of the turn
    # loop. Anything that isn't a two-item list/tuple simply means "no range": the whole file is returned.
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
''',
        True,
    ),
    (
        "2. agent_loop._execute_call: a tool that raises becomes a failed tool_result, not a dead session",
        AGENT_LOOP,
        '''    outcome = await _execute_call_inner(
        project_id, session_id, user_id, name, arguments, viewed_paths, merged_mcp, session, conversation_snapshot
    )
''',
        '''    try:
        outcome = await _execute_call_inner(
            project_id, session_id, user_id, name, arguments, viewed_paths, merged_mcp, session, conversation_snapshot
        )
    except Exception as exc:  # noqa: BLE001 — a tool that blows up is a failed RESULT the model can see, not a crashed turn
        # Without this the exception escaped to _run, which marked the session failed while the tool_call event
        # stayed dangling in the log. Crash recovery then re-ran that call at the start of EVERY later message,
        # hit the same exception, and the session could never take another turn.
        logger.exception("tool call %s failed for project %s", name, project_id)
        outcome = ExecutionOutcome(ok=False, error=f"{name} failed: {' '.join(str(exc).split())[:300] or type(exc).__name__}")
''',
        True,
    ),
    (
        "3. agent_loop._execute_call docstring: keep it truthful (optional)",
        AGENT_LOOP,
        '''If the underlying call raises, no row is written (the exception
    propagates to the turn loop, which records the failure as its own
    transcript event) — same behavior as before this labelling change; it was
    deliberately not widened here.''',
        '''A tool that raises is turned into a failed result (and audited as a
    failure) below, so one bad call can't crash the turn or leave a dangling
    tool_call in the log that crash recovery would re-run, and re-crash on, at
    the start of every later message.''',
        False,
    ),
    (
        "4. deploy_detection: constants for the static-site rule",
        DETECTION,
        '''_DEFAULT_PYTHON_PORT = 8000
''',
        '''_DEFAULT_PYTHON_PORT = 8000
_DEFAULT_STATIC_PORT = 8000
_STATIC_RUN_CMD = "python3 -m http.server $PORT"
''',
        True,
    ),
    (
        "5. deploy_detection: a plain index.html site is detected by rule, not by asking the model",
        DETECTION,
        '''        result = _detect_python_stack(scan)
        if result is not None:
            return result

    return None
''',
        '''        result = _detect_python_stack(scan)
        if result is not None:
            return result

    if _is_plain_static_site(scan):
        # `stack="python"` on purpose: the deploy_runs_stack_check constraint only allows nextjs/node/python/
        # dockerfile/llm_fallback, and a new value there needs a migration. The command is a stock Python file server.
        return StackDetectionResult(stack="python", build_cmd=None, run_cmd=_STATIC_RUN_CMD, port=_DEFAULT_STATIC_PORT)

    return None


def _is_plain_static_site(scan: dict) -> bool:
    """An index.html at the root and nothing that says "this needs a build or a server": no package.json (a Vite
    project also has an index.html at its root, and serving that raw is wrong), no requirements.txt/Procfile/
    manage.py/app.py/main.py. Anything else is left to the other rules or the model fallback. Before this rule a
    from-scratch static page depended on the fallback model happening to answer with a file server."""
    if "index.html" not in (scan.get("top_level_files") or []):
        return False
    if scan.get("package_json") is not None:
        return False
    return not any(scan.get(key) for key in ("requirements_txt", "procfile", "manage_py", "app_py", "main_py"))
''',
        True,
    ),
    (
        "6. system_prompt: PREVIEW_RULES block, placed after VISUAL_VERIFICATION",
        PROMPT,
        '''STATIC_BLOCK_ORDER = ['IDENTITY_AND_ROLE', 'AUTONOMY_AND_CAPABILITY_BOUNDARY', 'COMMUNICATION_STYLE', 'SECURITY', 'PROBLEM_SOLVING_WORKFLOW', 'TASK_MANAGEMENT', 'BASH_USAGE', 'VISUAL_VERIFICATION', 'VERSION_CONTROL', 'GITHUB_CONNECTOR', 'PLATFORM_CAPABILITIES']''',
        '''STATIC_PREVIEW_RULES = """<PREVIEW_RULES>
The person checks your work in the Live Preview, which has fixed limits. Build
within them, or say plainly in your report that something falls outside them.

- It serves one app, from the repository root. A project created here has no
  detection of subfolder apps, so do not split the work into frontend/ and
  backend/ folders unless the person asks for that, and then say that the
  preview will only show the root.
- Only one port is public. A second service (an API server, say) can be
  reached by the app from inside the workspace, never by the person's browser.
- The preview opens at "/" and has no address bar. Name the entry page
  index.html and link every other page from it with relative links.
- A plain site (HTML, CSS, JavaScript, no package.json or requirements.txt)
  is served as static files and edits show on reload. Anything that needs a
  build step or a server process only runs after the person clicks Deploy.
- The start command is chosen on the first Deploy and then reused. If you
  change the kind of project (plain files to a build step, for example), say
  so in your report, because the saved command may no longer fit.
</PREVIEW_RULES>"""

STATIC_BLOCK_ORDER = ['IDENTITY_AND_ROLE', 'AUTONOMY_AND_CAPABILITY_BOUNDARY', 'COMMUNICATION_STYLE', 'SECURITY', 'PROBLEM_SOLVING_WORKFLOW', 'TASK_MANAGEMENT', 'BASH_USAGE', 'VISUAL_VERIFICATION', 'PREVIEW_RULES', 'VERSION_CONTROL', 'GITHUB_CONNECTOR', 'PLATFORM_CAPABILITIES']''',
        True,
    ),
]


def main() -> int:
    by_file: dict[str, list] = {}
    for edit in EDITS:
        by_file.setdefault(edit[1], []).append(edit)

    skipped: list[str] = []
    for path, edits in by_file.items():
        p = Path(path)
        if not p.exists():
            print(f"SKIPPED {path}: not found. Run this from the repo root (the folder containing backend/).")
            skipped.append(path)
            continue
        raw = p.read_bytes().decode("utf-8")
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n")
        changed = 0
        failed = False
        for label, _path, old, new, required in edits:
            if new in text:
                print(f"already applied: {label}")
                continue
            count = text.count(old)
            if count != 1:
                msg = f"{label}: expected the original text exactly once, found {count}."
                if required:
                    print(f"SKIPPED {path}: {msg}")
                    failed = True
                    break
                print("warning (optional edit skipped):", msg)
                continue
            text = text.replace(old, new)
            changed += 1
            print(f"applied: {label}")
        if failed:
            skipped.append(path)
            continue
        if not changed:
            continue
        try:
            ast.parse(text)
        except SyntaxError as exc:
            print(f"SKIPPED {path}: result would not parse ({exc}).")
            skipped.append(path)
            continue
        p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
        print(f"wrote {path}")

    if skipped:
        print("\nNOT applied to:", ", ".join(skipped), "(your copy differs from GitHub main; send me that file)")
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
