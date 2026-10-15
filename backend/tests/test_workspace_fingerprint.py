"""§14.9 — the workspace fingerprint script, run in a REAL local bash and git (like test_deploy_pipeline's generated
scripts): a script that is only ever read is a script that's never been run."""
import os
import subprocess

import pytest

from app.services import workspace_fingerprint as fp


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout


def _hash(cwd) -> str | None:
    r = subprocess.run(["bash", "-c", fp.build_script()], cwd=cwd, capture_output=True, text=True)
    return fp.parse_output(r.returncode, r.stdout)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "app.js").write_text("console.log(1)\n")
    return tmp_path


def test_same_content_gives_the_same_hash_and_it_looks_like_a_git_hash(repo):
    a, b = _hash(repo), _hash(repo)
    assert a and a == b and len(a) in (40, 64)


def test_a_content_change_changes_it(repo):
    before = _hash(repo)
    (repo / "app.js").write_text("console.log(2)\n")
    assert _hash(repo) != before


def test_a_new_file_changes_it_and_removing_it_changes_it_back(repo):
    before = _hash(repo)
    (repo / "page.html").write_text("<p>hi</p>")
    assert _hash(repo) != before
    (repo / "page.html").unlink()
    assert _hash(repo) == before


def test_build_output_and_dependency_directories_do_not_count(repo):
    before = _hash(repo)
    for d in ("node_modules/left-pad", "dist", ".next/cache", "frontend/node_modules/x", "build"):
        (repo / d).mkdir(parents=True, exist_ok=True)
        (repo / d / "junk.js").write_text("x")
    assert _hash(repo) == before


def test_it_never_touches_the_real_index_or_head(repo):
    _git(repo, "add", "app.js")
    staged_before = _git(repo, "diff", "--cached", "--name-only")
    (repo / "new.txt").write_text("not staged")
    _hash(repo)
    assert _git(repo, "diff", "--cached", "--name-only") == staged_before        # the real index is exactly as it was
    assert "new.txt" in _git(repo, "status", "--porcelain")                        # and the new file is still untracked


def test_gitignored_files_do_not_count(repo):
    (repo / ".gitignore").write_text("secret.log\n")
    before = _hash(repo)
    (repo / "secret.log").write_text("changes constantly")
    assert _hash(repo) == before


def test_a_directory_that_is_not_a_git_repo_gives_none(tmp_path):
    r = subprocess.run(["bash", "-c", fp.build_script()], cwd=tmp_path, capture_output=True, text=True)
    assert fp.parse_output(r.returncode, r.stdout) is None


def test_parse_output_rejects_noise():
    assert fp.parse_output(0, "warning: something\n") is None
    assert fp.parse_output(1, "a" * 40) is None
    assert fp.parse_output(0, "x\n" + "a" * 40 + "\n") == "a" * 40
