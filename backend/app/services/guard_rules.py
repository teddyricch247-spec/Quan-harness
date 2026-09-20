"""
§14.3's heuristic guard and env isolation, plus §22's language detection —
extracted to a pure module (no app.config/app.db/httpx imports) specifically so
it can be unit tested in total isolation from the Fly/Supabase clients. See
backend/tests/test_heuristic_guard.py and test_execute_bash_env_isolation.py.
app/services/shell_tools.py imports everything here rather than redefining it.
"""
import json
import re
import shlex
from dataclasses import dataclass

REPO_ROOT = "/workspace/repo"  # duplicated literal, not import, to keep this module dependency-free — see workspace_paths.py, the source of truth

_CREDENTIAL_PATH_MARKERS = (".aws", ".ssh", ".netrc")
_GIT_REMOTE_SUBCOMMANDS = {"remote", "push", "pull", "fetch", "clone", "checkout", "branch", "switch"}
_SPLIT_ON = re.compile(r"&&|\|\||\||;|\n")
_FETCH_PIPE_RE = re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(sh|bash)\b")

_OUTPUT_MAX_LINES = 400
_OUTPUT_MAX_CHARS = 8000


@dataclass
class GuardResult:
    blocked: bool
    reason: str | None = None


def classify_command(command: str, known_secret_values: list[str] | None = None) -> GuardResult:
    """§14.3's six structural rules, checked in the order listed there. Returns
    the FIRST match — callers only need to know it's blocked and why, not every
    rule that happened to match."""
    known_secret_values = known_secret_values or []

    for literal in known_secret_values:
        if literal and literal in command:
            return GuardResult(True, "Command contains the literal value of a currently-resolved secret.")

    sub_commands = [c.strip() for c in _SPLIT_ON.split(command) if c.strip()]

    for sub in sub_commands:
        tokens = _safe_tokenize(sub)

        if "sudo" in tokens:
            return GuardResult(True, "sudo is not permitted.")

        for marker in _CREDENTIAL_PATH_MARKERS:
            if marker in sub:
                return GuardResult(True, f"References a known credential file location ({marker}).")

        for token in tokens:
            if _escapes_workspace(token):
                return GuardResult(True, f"Path '{token}' resolves outside the workspace root.")

        if _is_git_remote_or_branch_op(tokens):
            return GuardResult(True, "git operations targeting a remote or branch are not permitted here.")

    if _pipes_fetch_into_shell(command):
        return GuardResult(True, "Piping curl/wget output directly into a shell is not permitted.")

    return GuardResult(False)


def _safe_tokenize(sub_command: str) -> list[str]:
    try:
        return shlex.split(sub_command)
    except ValueError:
        # Unbalanced quoting or similar — can't tokenize safely, so treat every
        # whitespace-separated chunk as a token instead of silently skipping
        # the structural checks above.
        return sub_command.split()


def _escapes_workspace(token: str) -> bool:
    # Command substitution ($(...), backticks) genuinely can't be evaluated
    # statically — that's exactly why this is a heuristic, not a sandbox
    # boundary in itself. The boundary the *machine* actually enforces is
    # resolve_repo_path()/cwd (workspace_paths.py); this heuristic exists to
    # catch an obviously-bad call *before* it runs.
    if token.startswith("/") and not token.startswith(REPO_ROOT):
        return True
    parts = token.split("/")
    return ".." in parts


def _is_git_remote_or_branch_op(tokens: list[str]) -> bool:
    if "git" not in tokens:
        return False
    git_idx = tokens.index("git")
    remainder = set(tokens[git_idx + 1 :])
    return bool(remainder & _GIT_REMOTE_SUBCOMMANDS)


def _pipes_fetch_into_shell(command: str) -> bool:
    return bool(_FETCH_PIPE_RE.search(command))


def build_bash_env(project_secrets: dict[str, str], scratch_home: str) -> dict[str, str]:
    """§14.3: 'A minimal environment (PATH, HOME pointed at a scratch directory,
    LANG) — no credential of any kind is ever placed in it.' This function's
    signature IS the isolation guarantee: it has no parameter through which a
    GitHub or connector credential could ever arrive, so there's no call site
    that could pass one in even by mistake."""
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": scratch_home,
        "LANG": "C.UTF-8",
    }
    for name, value in project_secrets.items():
        if name in env:
            continue  # never let a secret's registered name shadow PATH/HOME/LANG
        env[name] = value
    return env


def referenced_secret_names(command: str, secret_names: list[str]) -> list[str]:
    return [name for name in secret_names if f"${name}" in command or "${" + name + "}" in command]


def mask_secrets(text: str, secret_values: dict[str, str]) -> str:
    masked = text
    for value in secret_values.values():
        if value:
            masked = masked.replace(value, "<secret-hidden>")
    return masked


def truncate_output(text: str) -> str:
    """§14.3: 'stdout/stderr captured and truncated (last ~400 lines or ~8,000
    characters, whichever is smaller).'"""
    lines = text.splitlines()
    if len(lines) > _OUTPUT_MAX_LINES:
        text = "\n".join(lines[-_OUTPUT_MAX_LINES:])
    if len(text) > _OUTPUT_MAX_CHARS:
        text = text[-_OUTPUT_MAX_CHARS:]
    return text


def detect_language(repo_listing: list[str]) -> str:
    """§22: 'detects project language via lockfiles/config — package.json plus
    an eslint config vs. requirements.txt/pyproject.toml.'"""
    names = set(repo_listing)
    has_js = "package.json" in names and bool(
        names & {".eslintrc", ".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs"}
    )
    has_py = bool(names & {"requirements.txt", "pyproject.toml"})
    if has_js and has_py:
        return "mixed"
    if has_js:
        return "js_ts"
    if has_py:
        return "python"
    return "none"


# detect_language only ever returns "js_ts"/"mixed" when an eslint config was
# already found in the repo root (above), so run_lint's js_ts branch always
# has a real project config to respect — there is no "no project config"
# case reachable through detect_language as written (see
# test_js_project_requires_both_package_json_and_eslint_config). ESLint's CLI
# has no "resolve my full config but only apply these rules" flag, so §22's
# "fatal-only subset of the project's own eslint config" is implemented by
# letting the config resolve normally — parser, plugins, parserOptions
# included, which is also what's needed to parse .tsx/.ts correctly at all —
# then filtering its own `--format json` output down to this set ourselves.
# The JS/TS analogue of _PY_FATAL_CODES in shell_tools.py: undefined names
# and similarly broken code, not style nitpicks. Fixed, not per-project
# configurable, same as the Python side.
JS_FATAL_RULES = frozenset({
    "no-undef",
    "no-dupe-keys",
    "no-dupe-args",
    "no-dupe-class-members",
    "no-dupe-else-if",
    "no-const-assign",
    "no-class-assign",
    "no-func-assign",
    "no-import-assign",
    "no-unreachable",
    "no-unsafe-negation",
    "no-unsafe-optional-chaining",
    "no-invalid-regexp",
    "no-this-before-super",
    "constructor-super",
    "for-direction",
    "valid-typeof",
    "use-isnan",
})


def filter_fatal_eslint_messages(eslint_json_stdout: str) -> list[dict]:
    """Takes eslint's own `--format json` stdout and returns only the
    messages that count as fatal under JS_FATAL_RULES, plus genuine parse
    failures (`fatal: true` — these carry no ruleId at all, since the file
    couldn't be parsed into an AST to run rules against in the first place;
    the JS/TS equivalent of a Python SyntaxError, always fatal regardless of
    rule set). Malformed input (eslint printing a startup error instead of
    JSON results, say) returns an empty list rather than raising — the
    caller already checks the process's own exit code for that case."""
    try:
        file_results = json.loads(eslint_json_stdout)
    except (json.JSONDecodeError, TypeError):
        return []
    fatal: list[dict] = []
    for file_result in file_results:
        file_path = file_result.get("filePath", "")
        for msg in file_result.get("messages", []):
            if msg.get("fatal") or msg.get("ruleId") in JS_FATAL_RULES:
                fatal.append({**msg, "filePath": file_path})
    return fatal


def format_fatal_eslint_messages(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        rule = msg.get("ruleId") or "parse-error"
        lines.append(f"{msg.get('filePath')}:{msg.get('line')}:{msg.get('column')} [{rule}] {msg.get('message')}")
    return "\n".join(lines)
