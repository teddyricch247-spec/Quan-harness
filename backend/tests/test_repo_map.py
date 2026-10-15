import subprocess

from app.services.repo_map import (
    SCAN_SCRIPT,
    RepoFile,
    build_adjacency,
    parse_scan_output,
    rank_and_budget,
    render_repo_map,
)

SAMPLE_SCAN_OUTPUT = """@@FILES@@
app/main.py
app/utils.py
README.md
@@PY@@
app/main.py:1:import app.utils
app/main.py:5:def start():
app/main.py:12:class Server:
app/utils.py:3:def helper():
@@JSTS@@
"""


def test_parse_scan_output_builds_one_entry_per_file():
    files = parse_scan_output(SAMPLE_SCAN_OUTPUT)
    assert [f.path for f in files] == ["app/main.py", "app/utils.py", "README.md"]


def test_parse_scan_output_attaches_signatures_to_the_right_file():
    files = parse_scan_output(SAMPLE_SCAN_OUTPUT)
    by_path = {f.path: f for f in files}
    assert any("def start():" in s for s in by_path["app/main.py"].signatures)
    assert any("class Server:" in s for s in by_path["app/main.py"].signatures)
    assert any("def helper():" in s for s in by_path["app/utils.py"].signatures)


def test_parse_scan_output_file_with_no_signatures_still_gets_an_entry():
    files = parse_scan_output(SAMPLE_SCAN_OUTPUT)
    readme = next(f for f in files if f.path == "README.md")
    assert readme.signatures == []


def test_parse_scan_output_empty_input():
    assert parse_scan_output("") == []


def test_parse_scan_output_ignores_signature_lines_for_unlisted_paths():
    raw = "@@FILES@@\na.py\n@@PY@@\nb.py:1:def ghost():\n@@JSTS@@\n"
    files = parse_scan_output(raw)
    assert len(files) == 1
    assert files[0].signatures == []


# --- build_adjacency ------------------------------------------------------

ADJACENCY_SCAN_OUTPUT = """@@FILES@@
app/services/agent_loop.py
app/services/checkpoints.py
app/services/file_tools.py
frontend/src/App.tsx
frontend/src/components/Button.tsx
frontend/src/unrelated.tsx
@@PY@@
app/services/agent_loop.py:9:async def run():
app/services/checkpoints.py:1:async def create_checkpoint():
app/services/file_tools.py:1:async def str_replace():
@@JSTS@@
frontend/src/App.tsx:4:export default function App() {}
frontend/src/components/Button.tsx:1:export default function Button() {}
@@PYIMPORTS@@
app/services/agent_loop.py:5:import app.services.checkpoints
app/services/agent_loop.py:6:from app.services import file_tools
app/services/agent_loop.py:7:import os
@@JSTSIMPORTS@@
frontend/src/App.tsx:1:import Button from './components/Button'
frontend/src/App.tsx:2:import React from 'react'
"""


def _adjacency_files() -> list[RepoFile]:
    return parse_scan_output(ADJACENCY_SCAN_OUTPUT)


def test_python_dotted_import_resolves_to_a_real_edge():
    adjacency = build_adjacency(_adjacency_files(), ADJACENCY_SCAN_OUTPUT)
    assert adjacency["app/services/agent_loop.py"] == {"app/services/checkpoints.py", "app/services/file_tools.py"}


def test_edges_are_symmetric():
    adjacency = build_adjacency(_adjacency_files(), ADJACENCY_SCAN_OUTPUT)
    assert adjacency["app/services/checkpoints.py"] == {"app/services/agent_loop.py"}
    assert adjacency["app/services/file_tools.py"] == {"app/services/agent_loop.py"}


def test_relative_jsts_import_resolves_across_directories():
    adjacency = build_adjacency(_adjacency_files(), ADJACENCY_SCAN_OUTPUT)
    assert adjacency["frontend/src/App.tsx"] == {"frontend/src/components/Button.tsx"}
    assert adjacency["frontend/src/components/Button.tsx"] == {"frontend/src/App.tsx"}


def test_stdlib_and_package_imports_produce_no_edge():
    adjacency = build_adjacency(_adjacency_files(), ADJACENCY_SCAN_OUTPUT)
    # "import os" and "from 'react'" never resolve to a repo file — neither
    # should silently attach itself to app/services/agent_loop.py or
    # frontend/src/App.tsx's edge sets.
    assert "os" not in adjacency
    assert "react" not in adjacency
    for neighbors in adjacency.values():
        assert "os" not in neighbors and "react" not in neighbors


def test_unrelated_file_gets_no_adjacency_entry_at_all():
    adjacency = build_adjacency(_adjacency_files(), ADJACENCY_SCAN_OUTPUT)
    assert "frontend/src/unrelated.tsx" not in adjacency


def test_import_of_a_path_not_in_the_scan_is_dropped_not_guessed():
    # file_tools.py *is* in this scan (see ADJACENCY_SCAN_OUTPUT), but if it
    # weren't, the import line referencing it must not invent a phantom path.
    raw = """@@FILES@@
a.py
@@PY@@
a.py:1:def f():
@@JSTS@@
@@PYIMPORTS@@
a.py:2:from app.services import nonexistent_module
@@JSTSIMPORTS@@
"""
    files = parse_scan_output(raw)
    adjacency = build_adjacency(files, raw)
    assert adjacency == {}


def test_new_import_markers_do_not_corrupt_existing_signature_parsing():
    # The regression this guards: before parse_scan_output's section
    # splitter knew about the two new import markers, lines under them fell
    # through into whichever section preceded them in SCAN_SCRIPT (JSTS
    # signatures) and got parsed as bogus extra "signatures."
    files = parse_scan_output(ADJACENCY_SCAN_OUTPUT)
    by_path = {f.path: f for f in files}
    assert by_path["frontend/src/App.tsx"].signatures == ["4: export default function App() {}"]
    assert by_path["app/services/agent_loop.py"].signatures == ["9: async def run():"]


def test_build_adjacency_on_empty_or_markerless_input_never_raises():
    assert build_adjacency([], "") == {}
    assert build_adjacency(_adjacency_files(), "no markers here at all") == {}


# --- rank_and_budget -----------------------------------------------------


def _files(n: int) -> list[RepoFile]:
    return [RepoFile(path=f"f{i}.py", signatures=[f"{i}: def f{i}():"]) for i in range(n)]


def test_small_repo_skips_ranking_and_keeps_every_signature():
    files = _files(10)
    entries = rank_and_budget(files, budget_tokens=1, small_repo_threshold=150)
    assert all(e.signatures is not None for e in entries)
    assert len(entries) == 10


def test_large_repo_ranks_opened_files_first():
    files = _files(200)
    entries = rank_and_budget(
        files,
        opened_paths={"f199.py"},
        budget_tokens=10,  # tiny — only room for a couple of full entries
        small_repo_threshold=150,
    )
    by_path = {e.path: e for e in entries}
    assert by_path["f199.py"].signatures is not None  # opened file always wins the budget


def test_large_repo_never_drops_a_file_entirely():
    files = _files(200)
    entries = rank_and_budget(files, budget_tokens=0, small_repo_threshold=150)
    assert len(entries) == 200
    assert all(e.path for e in entries)
    assert all(e.signatures is None for e in entries)  # budget exhausted immediately -> all path-only


def test_keyword_match_outranks_an_unrelated_file():
    files = [
        RepoFile(path="app/auth.py", signatures=["1: def login():"]),
        RepoFile(path="app/unrelated.py", signatures=["1: def noop():"]),
    ] + _files(150)  # push total over the small-repo threshold
    entries = rank_and_budget(files, task_keywords=["auth"], budget_tokens=10, small_repo_threshold=150)
    by_path = {e.path: e for e in entries}
    assert by_path["app/auth.py"].signatures is not None
    assert by_path["app/unrelated.py"].signatures is None


def test_adjacency_boosts_a_neighbor_of_an_opened_file():
    files = [
        RepoFile(path="app/a.py", signatures=["1: def a():"]),
        RepoFile(path="app/b.py", signatures=["1: def b():"]),
    ] + _files(150)
    entries = rank_and_budget(
        files,
        opened_paths={"app/a.py"},
        adjacency={"app/a.py": {"app/b.py"}},
        budget_tokens=12,
        small_repo_threshold=150,
    )
    by_path = {e.path: e for e in entries}
    assert by_path["app/a.py"].signatures is not None
    assert by_path["app/b.py"].signatures is not None


def test_original_order_preserved_for_entries_in_the_same_tier():
    files = _files(200)
    entries = rank_and_budget(files, budget_tokens=100000, small_repo_threshold=150)
    assert [e.path for e in entries] == [f.path for f in files]


# --- render_repo_map -------------------------------------------------------


def test_render_empty_repo():
    assert "empty" in render_repo_map([]).lower()


def test_render_includes_signatures_when_present():
    from app.services.repo_map import RankedEntry

    text = render_repo_map([RankedEntry(path="a.py", signatures=["1: def f():"])])
    assert "a.py:" in text
    assert "def f():" in text


def test_render_path_only_when_signatures_is_none():
    from app.services.repo_map import RankedEntry

    text = render_repo_map([RankedEntry(path="a.py", signatures=None)])
    assert text.strip() == "a.py"


# --- build_adjacency: source roots, tsconfig aliases, re-exports ------------
#
# Added when the import graph was found to resolve almost nothing on Quan's own
# layout (backend/app/... imported as `app....`; frontend importing through
# `@/`): 1 edge across the whole repo, against 248 after these cases were
# handled. Ground truth for that comparison was an `ast` parse of the real
# Python and a JSON read of the real tsconfig — 0 false positives, and every
# remaining miss was a documented limitation (multi-line imports, function-level
# imports, side-effect imports).

MONOREPO_SCAN_OUTPUT = """@@FILES@@
backend/app/main.py
backend/app/logging.py
backend/app/services/agent_loop.py
backend/app/services/checkpoints.py
backend/app/services/file_tools.py
backend/tests/test_checkpoints.py
frontend/tsconfig.json
frontend/app/page.tsx
frontend/lib/api.ts
frontend/components/index.ts
frontend/components/Button.tsx
web/app/other.tsx
@@PY@@
@@JSTS@@
@@PYIMPORTS@@
backend/app/services/agent_loop.py:3:from app.services import file_tools
backend/app/services/agent_loop.py:4:import logging
backend/tests/test_checkpoints.py:1:from app.services.checkpoints import create_checkpoint
@@JSTSIMPORTS@@
frontend/app/page.tsx:1:import { api } from '@/lib/api'
frontend/app/page.tsx:2:import { Button } from '@/components'
frontend/app/page.tsx:3:import { dialog } from '@radix-ui/react-dialog'
frontend/components/index.ts:1:export * from './Button'
web/app/other.tsx:1:import { api } from '@/lib/api'
@@TSCONFIG@@
frontend/tsconfig.json:5:    "paths": { "@/*": ["./*"] },
"""


def _monorepo_adjacency() -> dict[str, set[str]]:
    return build_adjacency(parse_scan_output(MONOREPO_SCAN_OUTPUT), MONOREPO_SCAN_OUTPUT)


def _adjacency_for(files: list[str], py_imports: str = "", jsts_imports: str = "", tsconfig: str = "") -> dict[str, set[str]]:
    raw = "@@FILES@@\n" + "\n".join(files) + f"\n@@PY@@\n@@JSTS@@\n@@PYIMPORTS@@\n{py_imports}\n@@JSTSIMPORTS@@\n{jsts_imports}\n@@TSCONFIG@@\n{tsconfig}\n"
    return build_adjacency(parse_scan_output(raw), raw)


def test_python_dotted_import_resolves_under_a_nested_source_root():
    # `app.services.file_tools` lives at backend/app/services/file_tools.py — the
    # source root is backend/, an ancestor of the importing file, not the repo root.
    adjacency = _monorepo_adjacency()
    assert "backend/app/services/file_tools.py" in adjacency["backend/app/services/agent_loop.py"]


def test_python_import_from_a_sibling_tests_directory_resolves_up_to_the_source_root():
    adjacency = _monorepo_adjacency()
    assert adjacency["backend/tests/test_checkpoints.py"] == {"backend/app/services/checkpoints.py"}


def test_single_word_python_import_never_matches_a_same_named_file_under_an_ancestor():
    # `import logging` is the stdlib. backend/app/logging.py exists, is an
    # ancestor-directory match for the importing file, and must NOT be linked —
    # that's the false-positive class the narrower single-word search prevents.
    adjacency = _monorepo_adjacency()
    assert "backend/app/logging.py" not in adjacency
    assert "backend/app/logging.py" not in adjacency["backend/app/services/agent_loop.py"]


def test_single_word_python_import_still_resolves_a_sibling_in_the_same_directory():
    adjacency = _adjacency_for(["pkg/a.py", "pkg/helper.py"], py_imports="pkg/a.py:1:import helper")
    assert adjacency == {"pkg/a.py": {"pkg/helper.py"}, "pkg/helper.py": {"pkg/a.py"}}


def test_python_import_of_a_module_not_under_any_ancestor_is_dropped():
    # deep/c/y.py exists, but `deep/` is not an ancestor directory of a/x.py, so
    # `import c.y` has no source root it could be relative to — no guessed edge.
    adjacency = _adjacency_for(["a/x.py", "deep/c/y.py"], py_imports="a/x.py:1:import c.y")
    assert adjacency == {}


def test_python_import_resolves_against_the_repo_root_from_any_depth():
    adjacency = _adjacency_for(["a/deep/x.py", "b/y.py"], py_imports="a/deep/x.py:1:import b.y")
    assert adjacency == {"a/deep/x.py": {"b/y.py"}, "b/y.py": {"a/deep/x.py"}}


def test_alias_import_resolves_through_the_nearest_tsconfig():
    adjacency = _monorepo_adjacency()
    assert "frontend/lib/api.ts" in adjacency["frontend/app/page.tsx"]


def test_alias_import_resolving_to_a_directory_uses_its_index_file():
    adjacency = _monorepo_adjacency()
    assert "frontend/components/index.ts" in adjacency["frontend/app/page.tsx"]


def test_alias_import_with_no_tsconfig_above_the_importing_file_is_dropped_not_guessed():
    # web/app/other.tsx also writes '@/lib/api', but no tsconfig sits above it —
    # frontend/'s config doesn't apply to it, so no edge to frontend/lib/api.ts.
    adjacency = _monorepo_adjacency()
    assert "web/app/other.tsx" not in adjacency


def test_scoped_npm_package_is_not_mistaken_for_an_alias():
    # '@radix-ui/react-dialog' starts with '@' but not '@/', so the '@/*' alias must not claim it.
    adjacency = _monorepo_adjacency()
    for neighbors in adjacency.values():
        assert not any("radix" in n for n in neighbors)


def test_reexport_line_creates_an_edge():
    adjacency = _monorepo_adjacency()
    assert adjacency["frontend/components/index.ts"] == {"frontend/components/Button.tsx", "frontend/app/page.tsx"}


def test_tsconfig_baseurl_is_applied_before_the_alias_target():
    adjacency = _adjacency_for(
        ["frontend/tsconfig.json", "frontend/src/lib/api.ts", "frontend/src/page.tsx"],
        jsts_imports="frontend/src/page.tsx:1:import { a } from '@/lib/api'",
        tsconfig='frontend/tsconfig.json:3:    "baseUrl": "src",\nfrontend/tsconfig.json:5:    "paths": { "@/*": ["./*"] }',
    )
    assert adjacency["frontend/src/page.tsx"] == {"frontend/src/lib/api.ts"}


def test_alias_targets_without_a_leading_dot_and_a_bare_star_target():
    files = ["ui/tsconfig.json", "ui/src/a.ts", "ui/b.ts", "ui/page.tsx"]
    adjacency = _adjacency_for(
        files,
        jsts_imports="ui/page.tsx:1:import a from '~/a'\nui/page.tsx:2:import b from '@/b'",
        tsconfig='ui/tsconfig.json:4:    "~/*": ["src/*"],\nui/tsconfig.json:5:    "@/*": ["*"]',
    )
    assert adjacency["ui/page.tsx"] == {"ui/src/a.ts", "ui/b.ts"}


def test_nearest_tsconfig_wins_outright_over_an_outer_one():
    files = ["tsconfig.json", "root/x.ts", "app/tsconfig.json", "app/page.tsx"]
    adjacency = _adjacency_for(
        files,
        jsts_imports="app/page.tsx:1:import x from '@/x'",
        tsconfig='tsconfig.json:2:    "@/*": ["./root/*"]\napp/tsconfig.json:2:    "~/*": ["./*"]',
    )
    # app/'s own config defines only '~/*'; the root config's '@/*' must not be reached through it.
    assert adjacency == {}


def test_tsconfig_line_for_a_path_not_in_the_scan_is_ignored():
    adjacency = _adjacency_for(
        ["ui/page.tsx", "ui/b.ts"],
        jsts_imports="ui/page.tsx:1:import b from '@/b'",
        tsconfig='ghost/tsconfig.json:2:    "@/*": ["./*"]',
    )
    assert adjacency == {}


def test_tsconfig_section_does_not_leak_into_signature_parsing():
    by_path = {f.path: f for f in parse_scan_output(MONOREPO_SCAN_OUTPUT)}
    assert by_path["frontend/tsconfig.json"].signatures == []
    assert by_path["frontend/app/page.tsx"].signatures == []


# --- SCAN_SCRIPT, executed for real -----------------------------------------


def _run_scan(root) -> str:
    return subprocess.run(["bash", "-c", SCAN_SCRIPT], cwd=root, capture_output=True, text=True, check=True).stdout


def _write(root, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def test_scan_script_never_descends_into_dependency_or_build_directories(tmp_path):
    _write(tmp_path, "app/main.py", "import os\ndef start():\n    pass\n")
    _write(tmp_path, "web/tsconfig.json", '{ "compilerOptions": { "paths": { "@/*": ["./*"] } } }\n')
    # everything below is something `npm install` / a build / a virtualenv puts in the workspace
    _write(tmp_path, "node_modules/pkg/index.js", "export function leaked() {}\n")
    _write(tmp_path, "node_modules/pkg/tsconfig.json", '{ "compilerOptions": { "paths": { "@/*": ["./evil/*"] } } }\n')
    _write(tmp_path, "web/node_modules/deep/index.js", "export function leakedDeep() {}\n")
    _write(tmp_path, ".next/server/page.js", "export function built() {}\n")
    _write(tmp_path, "app/__pycache__/main.cpython-312.pyc", "binary")
    _write(tmp_path, ".venv/lib/site.py", "def venv_thing():\n    pass\n")

    raw = _run_scan(tmp_path)
    paths = {f.path for f in parse_scan_output(raw)}
    assert paths == {"app/main.py", "web/tsconfig.json"}
    for excluded in ("node_modules", ".next", "__pycache__", ".venv"):
        assert excluded not in raw, f"{excluded} leaked into the scan output"


def test_scan_script_end_to_end_builds_real_edges_across_a_backend_and_frontend(tmp_path):
    _write(tmp_path, "backend/app/__init__.py", "")
    _write(tmp_path, "backend/app/services/__init__.py", "")
    _write(tmp_path, "backend/app/services/a.py", "from app.services import b\nimport json\n")
    _write(tmp_path, "backend/app/services/b.py", "def f():\n    pass\n")
    _write(tmp_path, "frontend/tsconfig.json", '{\n  "compilerOptions": {\n    "paths": { "@/*": ["./*"] }\n  }\n}\n')
    _write(tmp_path, "frontend/lib/api.ts", "export const api = 1\n")
    _write(tmp_path, "frontend/lib/index.ts", "export * from './api'\n")
    _write(tmp_path, "frontend/app/page.tsx", "import { api } from '@/lib/api'\nexport default function Page() {}\n")

    raw = _run_scan(tmp_path)
    adjacency = build_adjacency(parse_scan_output(raw), raw)
    assert "backend/app/services/b.py" in adjacency["backend/app/services/a.py"]
    assert adjacency["frontend/app/page.tsx"] == {"frontend/lib/api.ts"}
    assert adjacency["frontend/lib/index.ts"] == {"frontend/lib/api.ts"}  # re-export line
    assert "json" not in adjacency
