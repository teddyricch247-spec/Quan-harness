"""resolve_repo_path is the structural boundary the three file tools enforce
(vs. execute_bash's heuristic guard, which only pattern-matches) — a real path
join means it can be checked exactly rather than approximately."""
import pytest

from app.services.workspace_paths import REPO_ROOT, resolve_repo_path


def test_simple_relative_path_resolves_under_repo_root():
    assert resolve_repo_path("src/app.py") == f"{REPO_ROOT}/src/app.py"


def test_root_level_file_resolves():
    assert resolve_repo_path("README.md") == f"{REPO_ROOT}/README.md"


def test_absolute_path_is_rejected():
    with pytest.raises(ValueError):
        resolve_repo_path("/etc/passwd")


def test_empty_path_is_rejected():
    with pytest.raises(ValueError):
        resolve_repo_path("")


def test_simple_traversal_out_of_root_is_rejected():
    with pytest.raises(ValueError):
        resolve_repo_path("../outside.txt")


def test_traversal_that_nets_out_inside_root_is_allowed():
    # 'a/../b.py' legitimately resolves to 'b.py' within the root — only
    # traversal that would go *above* the root itself is rejected.
    assert resolve_repo_path("a/../b.py") == f"{REPO_ROOT}/b.py"


def test_deeply_nested_traversal_below_root_is_rejected():
    with pytest.raises(ValueError):
        resolve_repo_path("a/../../b.py")


def test_current_dir_segments_are_normalized_away():
    assert resolve_repo_path("./src/./app.py") == f"{REPO_ROOT}/src/app.py"


def test_bare_dot_resolves_to_root():
    assert resolve_repo_path(".") == REPO_ROOT
