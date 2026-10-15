"""
§17, dynamic context-assembly item 4 — the repo map: "file paths plus
top-level function and class signatures... not full file contents."

Split the same way as text_edit.py/file_tools.py: `rank_and_budget` and
`parse_scan_output` are pure and unit-tested directly (backend/tests/
test_repo_map.py); `scan_workspace`/`build_repo_map` are the I/O shell that
gathers real data via workspace_service.exec_in_workspace and hands it to
them. `render_repo_map` (also pure) turns the ranked result into the actual
text block system_prompt.py injects as REPO_CONTEXT.

Signature extraction below is regex-based (Python: `^(class |def |async def
)`; JS/TS: top-level `function`/`class`/exported `const =`), not a real
parse — the same "tree-sitter is optional, not a hard dependency" honest
fallback Phase 2 documented for §22's syntax check (see
/docs/PHASE2_NOTES.md's rough-edges section) applies here for the identical
reason (no verified `tree-sitter`/`tree-sitter-languages` install available
in this environment). Swap in a real tree-sitter walk here and in
text_edit.py together if that dependency ever gets installed for real — the
two call sites should use the same parser, not two different ones.

Same reasoning for "adjacent via the import/call graph": §17 asks for "a
lightweight PageRank-style pass over a symbol graph" — what's actually
implemented is a one-hop adjacency boost (a file sharing an edge with an
already-opened file ranks above one that doesn't), not a real PageRank
iteration. Directionally the same effect at the file counts this budget
realistically deals with (a few hundred files, §17's own threshold), and
honest about not being what the spec literally describes.

The adjacency graph itself is built by build_adjacency (below) — a second
regex pass, over the same scan the file listing and signatures already come
from, that turns each Python `import`/`from` line and each JS/TS
`import`/`export ... from`/`require` line into an edge between two paths that
both actually exist in this scan. Python dotted imports are resolved against
every ancestor directory of the importing file (so a `backend/app/...` layout
works, not only a repo-root one); JS/TS imports through a `paths` alias
(`@/lib/api`) are resolved against the nearest tsconfig.json/jsconfig.json. Still
an honest approximation, not a real parser: bare/third-party imports never
resolve to a repo file and are silently dropped, Python relative imports (`from
. import x`) and multi-line JS/TS imports aren't attempted, and a dynamic
`require(someVariable)` is invisible to a regex the same way it would be to a
naive static analyzer in any language — build_adjacency's own docstring lists
exactly what does and doesn't resolve. A missed edge just costs one fewer
tie-break signal (§17's tier 2 falls through to tier 3, "everything else"),
never a wrong one — this never invents an edge between two files that don't
actually reference each other. See /docs/PHASE3_NOTES.md.
"""
import posixpath
import re
from dataclasses import dataclass, field

from app.services.token_estimate import estimate_tokens

SMALL_REPO_FILE_THRESHOLD = 150
DEFAULT_BUDGET_TOKENS = 3000

_FILES_MARKER = "@@FILES@@"
_PY_MARKER = "@@PY@@"
_JSTS_MARKER = "@@JSTS@@"
_PY_IMPORTS_MARKER = "@@PYIMPORTS@@"
_JSTS_IMPORTS_MARKER = "@@JSTSIMPORTS@@"
_TSCONFIG_MARKER = "@@TSCONFIG@@"

# Directories no scan pass ever descends into: dependency installs, build
# output and VCS/scratch state are not the project's own code. Before this
# list existed, a routine `npm install` (which the agent is explicitly allowed
# to run — SECURITY block) put tens of thousands of node_modules paths into
# the file listing, pushing the repo map over §17's "small repo" threshold and
# burying real files under path-only noise, and made every grep pass below
# crawl them. `find` prunes by name (so it never even walks them); `grep -r`
# takes the same list as --exclude-dir.
_EXCLUDED_DIRS = (".git", ".qh-scratch-home", "node_modules", ".next", "__pycache__", ".venv")
_FIND_PRUNE = (
    r"\( " + " -o ".join(f"-name '{d}'" for d in _EXCLUDED_DIRS) + r" \) -prune -o -type f -print"
)
_GREP_EXCLUDES = " ".join(f"--exclude-dir='{d}'" for d in _EXCLUDED_DIRS)

# One combined shell script so a repo-map build costs exactly one
# exec_in_workspace round trip regardless of repo size — same reasoning as
# run_lint's own single-diff-then-branch approach (app/services/shell_tools.py).
#
# JS/TS import pass: `^(import|export).*from ` (not just `^import `) so a
# barrel/re-export line — `export * from './api'`, `export { x } from './y'` —
# counts as an edge too; index.ts re-export files are the connective tissue of
# most React/Next codebases and were invisible to the earlier `^import ` form.
# Still single-line only: a multi-line `import {\n a,\n b\n} from './x'` puts
# the `from` on a line that doesn't start with `import`, so it's missed (a
# missed edge, never a wrong one — see the module docstring).
#
# tsconfig pass: only the two kinds of line build_adjacency needs from a
# tsconfig.json/jsconfig.json — the `baseUrl` line and any `"<alias>/*":` key
# under `paths` — so the scan never has to ship whole config files back.
SCAN_SCRIPT = "".join(
    [
        f"echo '{_FILES_MARKER}'; ",
        rf"find . {_FIND_PRUNE} | sed 's#^\./##'; ",
        f"echo '{_PY_MARKER}'; ",
        rf"grep -rn {_GREP_EXCLUDES} --include='*.py' -E '^(class |def |async def )' . 2>/dev/null | sed 's#^\./##'; ",
        f"echo '{_JSTS_MARKER}'; ",
        rf"grep -rn {_GREP_EXCLUDES} --include='*.js' --include='*.jsx' --include='*.ts' --include='*.tsx' ",
        r"-E '^(export )?(default )?(async )?function |^(export )?(default )?class ",
        r"|^export const [A-Za-z_$][A-Za-z0-9_$]* *=' . 2>/dev/null | sed 's#^\./##'; ",
        f"echo '{_PY_IMPORTS_MARKER}'; ",
        rf"grep -rn {_GREP_EXCLUDES} --include='*.py' -E '^(import |from )' . 2>/dev/null | sed 's#^\./##'; ",
        f"echo '{_JSTS_IMPORTS_MARKER}'; ",
        rf"grep -rn {_GREP_EXCLUDES} --include='*.js' --include='*.jsx' --include='*.ts' --include='*.tsx' ",
        r"-E '^(import|export).*from |require\(' . 2>/dev/null | sed 's#^\./##'; ",
        f"echo '{_TSCONFIG_MARKER}'; ",
        rf"""grep -rn {_GREP_EXCLUDES} --include='tsconfig.json' --include='jsconfig.json' """,
        r"""-E '"baseUrl"|"[^"]+/\*"[[:space:]]*:' . 2>/dev/null | sed 's#^\./##'""",
    ]
)

_GREP_LINE_RE = re.compile(r"^([^:]+):(\d+):(.*)$")
_PY_IMPORT_LINE_RE = re.compile(r"^(?:import\s+([\w.]+))|(?:from\s+([\w.]+)\s+import\s+([\w.,\s*()]+))")
# Every `from '<spec>'` / `require('<spec>')` on one line, relative or not —
# whether a spec is a relative path, a tsconfig alias, or a bare package name
# is decided at resolution time, not here.
_JSTS_IMPORT_TARGET_RE = re.compile(r"""(?:from\s+|require\()\s*['"]([^'"]+)['"]""")
_JS_RESOLUTION_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
_TS_BASEURL_RE = re.compile(r'"baseUrl"\s*:\s*"([^"]*)"')
_TS_ALIAS_RE = re.compile(r'"([^"]+)/\*"\s*:\s*\[([^\]]*)')
_QUOTED_RE = re.compile(r'"([^"]*)"')


@dataclass
class RepoFile:
    path: str
    signatures: list[str] = field(default_factory=list)


@dataclass
class RankedEntry:
    path: str
    signatures: list[str] | None  # None = degraded to path-only for this step


_ALL_MARKERS = (_FILES_MARKER, _PY_MARKER, _JSTS_MARKER, _PY_IMPORTS_MARKER, _JSTS_IMPORTS_MARKER, _TSCONFIG_MARKER)


def _split_sections(raw: str) -> dict[str, str]:
    """Splits SCAN_SCRIPT's stdout on its six `echo '@@MARKER@@'` lines.
    Shared by parse_scan_output and build_adjacency so both agree on where
    one section ends and the next begins — critical now that there are three
    more markers than there used to be: without this, an import or tsconfig
    line would fall through into whichever section came right before it in
    the script and get fed to the wrong parser, corrupting it. A marker
    missing from `raw` entirely just leaves that section empty."""
    sections = {marker: "" for marker in _ALL_MARKERS}
    current = None
    for line in raw.splitlines():
        if line in sections:
            current = line
            continue
        if current is not None:
            sections[current] += line + "\n"
    return sections


def parse_scan_output(raw: str) -> list[RepoFile]:
    """Parses SCAN_SCRIPT's stdout into one RepoFile per path, in the order
    `find` produced (a file with no matched signatures — a config file, a
    non-Python/JS/TS source file, or a source file with none of the matched
    top-level shapes — still gets an entry, with an empty signatures list)."""
    sections = _split_sections(raw)

    files: dict[str, RepoFile] = {}
    order: list[str] = []
    for path in (p for p in sections[_FILES_MARKER].splitlines() if p.strip()):
        if path not in files:
            files[path] = RepoFile(path=path)
            order.append(path)

    for section in (sections[_PY_MARKER], sections[_JSTS_MARKER]):
        for line in section.splitlines():
            match = _GREP_LINE_RE.match(line)
            if not match:
                continue
            path, lineno, content = match.groups()
            entry = files.get(path)
            if entry is None:  # signature line for a path `find` didn't list — ignore defensively
                continue
            entry.signatures.append(f"{lineno}: {content.strip()}")

    return [files[p] for p in order]


def _ancestor_dirs(path: str) -> list[str]:
    """Every directory from the file's own one up to the repo root, deepest
    first, the root written as "" — `backend/app/x.py` ->
    `["backend/app", "backend", ""]`."""
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]


def _python_module_to_candidate_paths(module: str) -> list[str]:
    """foo.bar.baz -> ["foo/bar/baz.py", "foo/bar/baz/__init__.py"] — both
    proposed since a dotted module can be either a plain module file or a
    package directory; the caller only keeps whichever (if either) is
    actually in this scan's file listing."""
    as_path = module.replace(".", "/")
    return [f"{as_path}.py", f"{as_path}/__init__.py"]


def _python_search_roots(importing_path: str, module: str) -> list[str]:
    """Where an absolute `import <module>` written in `importing_path` could
    plausibly be rooted, deepest first ("" = the repo root).

    A Python import path is relative to a source root (a `sys.path` entry),
    which is rarely the repo root itself — Quan's own backend is
    `backend/app/services/x.py`, imported as `app.services.x`, so resolving
    only against the repo root found essentially no edges at all. A source root
    is, in practice, always an *ancestor directory of the file doing the
    importing*, so a dotted module (`app.services.x`) is tried against every
    ancestor of the importing file, deepest first.

    A single-word module (`import json`, `import logging`, `from config import
    x`) is deliberately held to a much narrower search — the importing file's
    own directory, and the repo root — because a bare name overwhelmingly means
    the stdlib or a third-party package, and letting it match a same-named file
    under any ancestor would attach `import logging` to an unrelated
    `backend/app/logging.py`. A dotted name has no such collision problem: it
    only resolves when the whole directory path exists in this repo."""
    ancestors = _ancestor_dirs(importing_path)
    if "." in module:
        return ancestors
    own_dir = ancestors[0]
    return [own_dir, ""] if own_dir else [""]


def _resolve_python_import(importing_path: str, content: str, known_paths: set[str]) -> list[str]:
    """`content` is one grep-matched import line's text (`import foo.bar` /
    `from foo.bar import baz, qux`), written in `importing_path`. Returns every
    repo path this line resolves to that's actually present in known_paths —
    usually zero or one, occasionally more than one for a multi-name `from`
    import where several of the imported names are themselves submodules.
    Deliberately does not attempt a leading-dot relative import (`from . import
    x`); see build_adjacency's docstring."""
    match = _PY_IMPORT_LINE_RE.match(content.strip())
    if not match:
        return []
    plain_import, from_module, imported_names = match.groups()

    modules: list[str] = []
    if plain_import:
        modules.append(plain_import)
    if from_module:
        modules.append(from_module)
        for raw_name in imported_names.split(","):
            name = raw_name.strip().split(" as ")[0].strip().strip("()").strip()
            if name and name != "*" and name.replace("_", "a").isalnum():
                modules.append(f"{from_module}.{name}")

    resolved: list[str] = []
    for module in modules:
        roots = _python_search_roots(importing_path, module)
        for candidate in _python_module_to_candidate_paths(module):
            for root in roots:
                full = f"{root}/{candidate}" if root else candidate
                if full in known_paths:
                    if full not in resolved:
                        resolved.append(full)
                    break  # deepest root wins for this candidate; don't also count a shallower one
    return resolved


def _first_existing_js_path(joined: str, known_paths: set[str]) -> str | None:
    """`joined` is a normalized repo-relative path with no extension
    guaranteed. Tries it as given, then with each JS/TS extension appended,
    then as a directory's `index.*` — the same resolution order a bundler
    uses, just without ever touching node_modules or a real filesystem."""
    candidates = [joined]
    candidates.extend(joined + ext for ext in _JS_RESOLUTION_EXTENSIONS)
    candidates.extend(posixpath.join(joined, "index" + ext) for ext in _JS_RESOLUTION_EXTENSIONS)
    for candidate in candidates:
        if candidate in known_paths:
            return candidate
    return None


def _resolve_js_import(importing_path: str, raw_target: str, known_paths: set[str]) -> str | None:
    """`raw_target` is the literal string inside `from '...'`/`require('...')`
    — only a relative one (starts with `.`) is resolved here; an alias
    (`@/lib/api`) goes through `_resolve_alias_import`, and a bare specifier
    (`from 'react'`) can never be a file in this repo."""
    if not raw_target.startswith("."):
        return None
    base_dir = posixpath.dirname(importing_path)
    return _first_existing_js_path(posixpath.normpath(posixpath.join(base_dir, raw_target)), known_paths)


@dataclass
class _TsConfig:
    """What build_adjacency needs from one tsconfig.json/jsconfig.json:
    `baseUrl` (paths are resolved against it when set, else against the config
    file's own directory) and its `paths` aliases, each as a prefix (the
    `"@/*"` key minus its `/*`) mapped to its target directories (each target
    minus its trailing `/*`)."""

    base_url: str = "."
    aliases: dict[str, list[str]] = field(default_factory=dict)


def _parse_tsconfigs(section: str, known_paths: set[str]) -> dict[str, _TsConfig]:
    """Keyed by the config's own directory ("" = repo root). Reads only the
    `baseUrl` line and single-line `"<alias>/*": [...]` entries SCAN_SCRIPT's
    tsconfig pass grepped out — see build_adjacency's docstring for what that
    does and doesn't cover."""
    configs: dict[str, _TsConfig] = {}
    for line in section.splitlines():
        match = _GREP_LINE_RE.match(line)
        if not match:
            continue
        path, _lineno, content = match.groups()
        if path not in known_paths:
            continue
        config = configs.setdefault(posixpath.dirname(path), _TsConfig())
        base = _TS_BASEURL_RE.search(content)
        if base:
            config.base_url = base.group(1) or "."
        for alias in _TS_ALIAS_RE.finditer(content):
            prefix, raw_targets = alias.groups()
            targets: list[str] = []
            for target in _QUOTED_RE.findall(raw_targets):
                target = target[:-2] if target.endswith("/*") else target
                targets.append("." if target == "*" else target)
            if targets:
                config.aliases[prefix] = targets
    return configs


def _resolve_alias_import(
    importing_path: str, spec: str, configs: dict[str, _TsConfig], known_paths: set[str]
) -> str | None:
    """`spec` like `@/lib/api`, resolved against the *nearest* tsconfig/
    jsconfig above the importing file (the same file TypeScript itself would
    use for it) — its alias prefixes, joined onto its baseUrl (or its own
    directory when it has none)."""
    for config_dir in _ancestor_dirs(importing_path):
        config = configs.get(config_dir)
        if config is None:
            continue
        for prefix, targets in config.aliases.items():
            if not spec.startswith(prefix + "/"):
                continue
            rest = spec[len(prefix) + 1 :]
            for target in targets:
                joined = posixpath.normpath(posixpath.join(config_dir, config.base_url, target, rest))
                found = _first_existing_js_path(joined, known_paths)
                if found:
                    return found
        return None  # nearest config wins outright — never fall through to an outer one
    return None


def build_adjacency(files: list[RepoFile], raw: str) -> dict[str, set[str]]:
    """§17 tier 2: "adjacent to an opened file via the import graph." One
    more regex pass over the same SCAN_SCRIPT output parse_scan_output
    already consumed, this time over the `import`/`from`/`require` lines —
    turns each one that resolves to a real file in this scan into a
    symmetric edge (A imports B ⇒ A and B are each in the other's
    adjacency set; §17's own framing is "shares an edge with," not a
    directed relationship). Every resolution failure is silently dropped
    rather than guessed at (see module docstring). Safe to call with an empty
    or marker-less `raw`: returns {}.

    What resolves: Python absolute imports (dotted modules against any ancestor
    directory of the importing file — see `_python_search_roots`); relative
    JS/TS imports; JS/TS imports through a `paths` alias defined on one line of
    the nearest tsconfig.json/jsconfig.json (e.g. `@/lib/api`); and re-exports
    (`export * from './x'`).

    What doesn't: bare package imports; Python relative imports (`from . import
    x`); a `paths` entry whose alias and target array span several lines, or a
    `paths` array with more than one target on a later line; `baseUrl`-relative
    bare imports (`import x from 'lib/api'`); a tsconfig reached only through
    `extends`; multi-line JS/TS imports; and dynamic `import()`/
    `require(variable)`."""
    sections = _split_sections(raw)
    known_paths = {f.path for f in files}
    ts_configs = _parse_tsconfigs(sections[_TSCONFIG_MARKER], known_paths)
    adjacency: dict[str, set[str]] = {}

    def _add_edge(a: str, b: str) -> None:
        if a == b:
            return
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    for line in sections[_PY_IMPORTS_MARKER].splitlines():
        match = _GREP_LINE_RE.match(line)
        if not match:
            continue
        path, _lineno, content = match.groups()
        if path not in known_paths:
            continue
        for target in _resolve_python_import(path, content, known_paths):
            _add_edge(path, target)

    for line in sections[_JSTS_IMPORTS_MARKER].splitlines():
        match = _GREP_LINE_RE.match(line)
        if not match:
            continue
        path, _lineno, content = match.groups()
        if path not in known_paths:
            continue
        for spec in _JSTS_IMPORT_TARGET_RE.findall(content):
            target = _resolve_js_import(path, spec, known_paths) or _resolve_alias_import(path, spec, ts_configs, known_paths)
            if target:
                _add_edge(path, target)

    return adjacency


def _matches_keyword(repo_file: RepoFile, keywords: list[str]) -> bool:
    if not keywords:
        return False
    haystack = (repo_file.path + " " + " ".join(repo_file.signatures)).lower()
    return any(kw.lower() in haystack for kw in keywords if kw.strip())


def _rank_tier(repo_file: RepoFile, opened_paths: set[str], keywords: list[str], adjacency: dict[str, set[str]]) -> int:
    """Lower tier number ranks higher. Order matches §17's own list:
    (0) already opened/edited this session, (1) keyword match,
    (2) adjacent to an opened file via the import graph, (3) everything else."""
    if repo_file.path in opened_paths:
        return 0
    if _matches_keyword(repo_file, keywords):
        return 1
    neighbors = adjacency.get(repo_file.path, set())
    if neighbors & opened_paths:
        return 2
    return 3


def rank_and_budget(
    files: list[RepoFile],
    opened_paths: set[str] | None = None,
    task_keywords: list[str] | None = None,
    adjacency: dict[str, set[str]] | None = None,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    small_repo_threshold: int = SMALL_REPO_FILE_THRESHOLD,
) -> list[RankedEntry]:
    """§17: below `small_repo_threshold` files, skip ranking and include every
    file's full signatures — ranking machinery is pure overhead at that size.
    Above it, rank highest-first and spend the budget on full signatures;
    once spent, remaining files still appear, path-only (never dropped)."""
    opened_paths = opened_paths or set()
    task_keywords = task_keywords or []
    adjacency = adjacency or {}

    if len(files) <= small_repo_threshold:
        return [RankedEntry(path=f.path, signatures=list(f.signatures)) for f in files]

    ranked = sorted(
        enumerate(files),
        key=lambda pair: (_rank_tier(pair[1], opened_paths, task_keywords, adjacency), pair[0]),
    )

    entries: list[RankedEntry] = [RankedEntry(path="", signatures=None)] * len(files)
    spent = 0
    for original_index, repo_file in ranked:
        cost = estimate_tokens(repo_file.path + "\n" + "\n".join(repo_file.signatures))
        if spent + cost <= budget_tokens:
            entries[original_index] = RankedEntry(path=repo_file.path, signatures=list(repo_file.signatures))
            spent += cost
        else:
            entries[original_index] = RankedEntry(path=repo_file.path, signatures=None)
    return entries


def render_repo_map(entries: list[RankedEntry]) -> str:
    """Pure formatting — the text that goes into the system prompt's
    REPO_CONTEXT dynamic section (§18)."""
    if not entries:
        return "(empty repository)"
    lines = []
    for entry in entries:
        if entry.signatures is None:
            lines.append(entry.path)
        elif entry.signatures:
            lines.append(entry.path + ":")
            lines.extend(f"    {sig}" for sig in entry.signatures)
        else:
            lines.append(entry.path)
    return "\n".join(lines)


async def build_repo_map(
    project_id: str,
    opened_paths: set[str] | None = None,
    task_keywords: list[str] | None = None,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> str:
    """I/O shell — one exec_in_workspace round trip, then pure parsing/ranking/
    rendering. Builds the one-hop import adjacency (build_adjacency) from the
    same scan and passes it through to rank_and_budget's tier-2 tie-break —
    see the module docstring for what this is and isn't. Regenerated fresh
    every step per §17 — deliberately not cached."""
    from app.services import workspace_service  # local import: keeps this I/O dependency out of the pure-logic import graph
    from app.services.workspace_paths import REPO_ROOT

    result = await workspace_service.exec_in_workspace(
        project_id, ["bash", "-c", SCAN_SCRIPT], timeout=30, cwd=REPO_ROOT
    )
    files = parse_scan_output(result.stdout)
    adjacency = build_adjacency(files, result.stdout)
    entries = rank_and_budget(
        files, opened_paths=opened_paths, task_keywords=task_keywords, adjacency=adjacency, budget_tokens=budget_tokens
    )
    return render_repo_map(entries)
