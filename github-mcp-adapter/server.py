"""
Quan Adaptor
------------------------
A remote MCP server that lets Claude.ai (or any MCP client) work
against your GitHub repos, Vercel projects, and Supabase Edge Function
secrets, gated behind a single Supabase Auth grant acting as an OAuth
2.1 authorization server — one approval covers all three, since every
tool below is registered on the same server.

    Claude.ai --OAuth-->                   Supabase   (issues a token; you approve the grant, once)
    Claude.ai --MCP call, bearer token-->  this server (Render)
    this server --verifies token via Supabase JWKS--> runs a tool
    this server --PAT-->                   GitHub API
    this server --token-->                 Vercel API
    this server --token-->                 Supabase Management API

The internal server name is still "quan-github-mcp" — left as-is so
Claude.ai's existing connector registration for it doesn't need to be
redone. It's cosmetic only; rename it later if you want, there's no
functional reason to.

/login and /oauth/consent are plain, unauthenticated HTTP routes that
Supabase's OAuth Server redirects the browser to mid-flow. See
README.md for the one-time Supabase/Render/Claude.ai setup this
depends on, and for the full tool reference.
"""

import os
from pathlib import Path

import requests
from fastmcp import FastMCP
from fastmcp.server.auth.providers.supabase import SupabaseProvider
from github import Github, Auth, UnknownObjectException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

# ---- Configuration ---------------------------------------------------

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
VERCEL_TOKEN = os.environ["VERCEL_TOKEN"]
VERCEL_TEAM_ID = os.environ.get("VERCEL_TEAM_ID", "")
SUPABASE_ACCESS_TOKEN = os.environ["SUPABASE_ACCESS_TOKEN"]
PORT = int(os.environ.get("PORT", 8080))

# Render sets RENDER_EXTERNAL_URL automatically for every web service.
# Override with BASE_URL if running locally or deploying elsewhere.
BASE_URL = os.environ.get("BASE_URL") or os.environ.get(
    "RENDER_EXTERNAL_URL", f"http://localhost:{PORT}"
)

STATIC_DIR = Path(__file__).parent / "static"

# ---- Auth + server -----------------------------------------------------

auth = SupabaseProvider(project_url=SUPABASE_URL, base_url=BASE_URL)
mcp = FastMCP(
    "quan-github-mcp",
    auth=auth,
    instructions=(
        "Tools for working against GitHub repos, Vercel projects, and "
        "Supabase Edge Function secrets on behalf of their owner. This "
        "server runs on a free hosting tier that sleeps after ~15 "
        "minutes idle. If a tool call is unusually slow (tens of "
        "seconds) or times out on the FIRST call in a while, that is "
        "almost always the server waking up, not a real failure: wait "
        "and retry the same call once before reporting an error to the "
        "user. A second failure in a row means something is actually "
        "wrong, not just asleep."
    ),
)

gh = Github(auth=Auth.Token(GITHUB_TOKEN))

VERCEL_API_BASE = "https://api.vercel.com"
SUPABASE_MGMT_API_BASE = "https://api.supabase.com"


def _guard_not_default_branch(repo, branch: str, action: str) -> None:
    """Internal helper (not a tool). Raise if branch is repo's default branch."""
    if branch == repo.default_branch:
        raise ValueError(
            f"Refusing to {action} '{branch}': it's {repo.full_name}'s default "
            f"branch. This adapter never {action}s a default branch — that's a "
            f"hard rule with no override, not a confirmation step."
        )


def _vercel_request(method: str, path: str, **kwargs) -> dict:
    """Internal helper (not a tool). Calls the Vercel REST API. Raises
    with the actual response body on failure instead of a bare status
    code, so a bad call is debuggable instead of a dead end."""
    params = kwargs.pop("params", None) or {}
    if VERCEL_TEAM_ID:
        params["teamId"] = VERCEL_TEAM_ID
    resp = requests.request(
        method,
        f"{VERCEL_API_BASE}{path}",
        headers={"Authorization": f"Bearer {VERCEL_TOKEN}"},
        params=params,
        timeout=30,
        **kwargs,
    )
    if not resp.ok:
        raise ValueError(f"Vercel API {method} {path} failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json() if resp.content else {}


def _supabase_mgmt_request(method: str, path: str, **kwargs) -> dict:
    """Internal helper (not a tool). Calls the Supabase Management API.
    Raises with the actual response body on failure instead of a bare
    status code, so a bad call is debuggable instead of a dead end."""
    resp = requests.request(
        method,
        f"{SUPABASE_MGMT_API_BASE}{path}",
        headers={"Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}"},
        timeout=30,
        **kwargs,
    )
    if not resp.ok:
        raise ValueError(f"Supabase Management API {method} {path} failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json() if resp.content else {}


# =====================================================================
# Repository & code browsing
# =====================================================================

@mcp.tool
def list_my_repos(limit: int = 20) -> list[str]:
    """List repositories the configured GitHub token can access.

    Ordered by most recently pushed first. Includes repos you own,
    collaborate on, and can reach via organization membership.

    Args:
        limit: Maximum number of repositories to return.

    Returns:
        A list of "owner/name" identifiers, e.g. ["octocat/hello-world"].
    """
    repos = gh.get_user().get_repos(sort="pushed", direction="desc")
    return [r.full_name for r in repos[:limit]]


@mcp.tool
def get_repo(repo: str) -> dict:
    """Get metadata about a repository.

    Args:
        repo: Repository identifier in "owner/name" format.

    Returns:
        A dict with full_name, description, default_branch, private,
        fork, language, open_issues_count, stargazers_count, html_url,
        and pushed_at (ISO 8601, or null).
    """
    r = gh.get_repo(repo)
    return {
        "full_name": r.full_name,
        "description": r.description,
        "default_branch": r.default_branch,
        "private": r.private,
        "fork": r.fork,
        "language": r.language,
        "open_issues_count": r.open_issues_count,
        "stargazers_count": r.stargazers_count,
        "html_url": r.html_url,
        "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
    }


@mcp.tool
def get_repo_tree(repo: str, ref: str = "", path: str = "") -> dict:
    """List every file and directory in a repository, recursively.

    Use this before get_file to discover what exists in a repo you
    haven't read yet — get_file needs an exact path, this finds it.

    Args:
        repo: Repository identifier in "owner/name" format.
        ref: Branch, tag, or commit SHA to read the tree from. Defaults
            to the repository's default branch.
        path: If set, only entries whose path starts with this prefix
            are returned, e.g. "src/" to scope to one directory.

    Returns:
        A dict with "truncated" (bool — true if GitHub capped the raw
        result before the path filter was applied, meaning some
        matches may be missing) and "entries": a list of dicts with
        "path", "type" ("blob" for a file, "tree" for a directory),
        and "size" (bytes, files only, otherwise null). Capped at 1000
        entries after filtering.
    """
    r = gh.get_repo(repo)
    commit_sha = r.get_commit(ref or r.default_branch).sha
    tree = r.get_git_tree(commit_sha, recursive=True)
    entries = [
        {"path": el.path, "type": el.type, "size": getattr(el, "size", None)}
        for el in tree.tree
        if not path or el.path.startswith(path)
    ]
    return {"truncated": tree.truncated, "entries": entries[:1000]}


@mcp.tool
def search_code(query: str, repo: str = "") -> list[dict]:
    """Search source code on GitHub.

    Args:
        query: A GitHub code search query, e.g. "def handle_webhook".
            GitHub's own search qualifiers (language:, path:,
            extension:, etc.) can be included directly in this string.
        repo: If set, restricts the search to this "owner/name" repo
            instead of everywhere the token has access.

    Returns:
        A list of dicts with "repo", "path", and "html_url", capped at 20 matches.
    """
    full_query = f"{query} repo:{repo}" if repo else query
    results = gh.search_code(full_query)
    return [
        {"repo": item.repository.full_name, "path": item.path, "html_url": item.html_url}
        for item in results[:20]
    ]


@mcp.tool
def list_branches(repo: str, limit: int = 50) -> list[dict]:
    """List branches in a repository.

    Args:
        repo: Repository identifier in "owner/name" format.
        limit: Maximum number of branches to return.

    Returns:
        A list of dicts with "name", "commit_sha", and "protected" (bool).
    """
    r = gh.get_repo(repo)
    branches = r.get_branches()
    return [
        {"name": b.name, "commit_sha": b.commit.sha, "protected": b.protected}
        for b in branches[:limit]
    ]


# =====================================================================
# Commit history
# =====================================================================

@mcp.tool
def list_commits(repo: str, branch: str = "", path: str = "", limit: int = 20) -> list[dict]:
    """List recent commits, newest first.

    Args:
        repo: Repository identifier in "owner/name" format.
        branch: Branch, tag, or commit SHA to start from. Defaults to
            the repository's default branch.
        path: If set, only commits that touched this file or directory are returned.
        limit: Maximum number of commits to return.

    Returns:
        A list of dicts with "sha", "message" (first line only),
        "author", "date" (ISO 8601), and "html_url".
    """
    r = gh.get_repo(repo)
    kwargs = {"sha": branch} if branch else {}
    if path:
        kwargs["path"] = path
    commits = r.get_commits(**kwargs)
    return [
        {
            "sha": c.sha,
            "message": c.commit.message.split("\n", 1)[0],
            "author": c.commit.author.name if c.commit.author else None,
            "date": c.commit.author.date.isoformat() if c.commit.author else None,
            "html_url": c.html_url,
        }
        for c in commits[:limit]
    ]


@mcp.tool
def get_commit(repo: str, sha: str) -> dict:
    """Get full details of a single commit, including which files it changed.

    Args:
        repo: Repository identifier in "owner/name" format.
        sha: Commit SHA, full or abbreviated.

    Returns:
        A dict with "sha", "message", "author", "html_url", and
        "files" — a list of dicts with "filename", "status" ("added",
        "modified", "removed", or "renamed"), "additions",
        "deletions", and "patch" (unified diff for that file, if
        GitHub provides one).
    """
    r = gh.get_repo(repo)
    c = r.get_commit(sha)
    return {
        "sha": c.sha,
        "message": c.commit.message,
        "author": c.commit.author.name if c.commit.author else None,
        "html_url": c.html_url,
        "files": [
            {
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "patch": getattr(f, "patch", None),
            }
            for f in c.files
        ],
    }


# =====================================================================
# File contents
# =====================================================================

@mcp.tool
def get_file(repo: str, path: str, ref: str = "") -> str:
    """Read a text file's full contents.

    Args:
        repo: Repository identifier in "owner/name" format.
        path: File path relative to the repository root.
        ref: Branch, tag, or commit SHA to read from. Defaults to the
            repository's default branch.

    Returns:
        The file's contents, decoded as UTF-8.
    """
    r = gh.get_repo(repo)
    contents = r.get_contents(path, ref=ref) if ref else r.get_contents(path)
    if isinstance(contents, list):
        raise ValueError(
            f"'{path}' is a directory, not a file. Use get_repo_tree to list "
            f"its contents, then call get_file on one of those paths."
        )
    return contents.decoded_content.decode("utf-8")


@mcp.tool
def create_or_update_file(repo: str, path: str, content: str, message: str, branch: str) -> dict:
    """Create a new file, or overwrite an existing one, in a single commit.

    Args:
        repo: Repository identifier in "owner/name" format.
        path: File path relative to the repository root.
        content: The full new text content of the file — not a diff,
            this replaces the entire file.
        message: The commit message.
        branch: Branch to commit to. Must already exist; use
            create_branch first if you need a new one.

    Returns:
        A dict with "commit_sha" and "content_url" (a link to the file at this commit).
    """
    r = gh.get_repo(repo)
    try:
        existing = r.get_contents(path, ref=branch)
        result = r.update_file(path, message, content, existing.sha, branch=branch)
    except UnknownObjectException:
        result = r.create_file(path, message, content, branch=branch)
    return {
        "commit_sha": result["commit"].sha,
        "content_url": result["content"].html_url,
    }


@mcp.tool
def delete_file(repo: str, path: str, message: str, branch: str) -> dict:
    """Delete a file in a single commit.

    Args:
        repo: Repository identifier in "owner/name" format.
        path: File path relative to the repository root.
        message: The commit message.
        branch: Branch to commit the deletion to.

    Returns:
        A dict with "commit_sha".
    """
    r = gh.get_repo(repo)
    existing = r.get_contents(path, ref=branch)
    result = r.delete_file(path, message, existing.sha, branch=branch)
    return {"commit_sha": result["commit"].sha}


# =====================================================================
# Branches
# =====================================================================

@mcp.tool
def create_branch(repo: str, new_branch: str, from_branch: str) -> dict:
    """Create a new branch, pointed at the current tip of an existing one.

    Args:
        repo: Repository identifier in "owner/name" format.
        new_branch: Name for the new branch.
        from_branch: Existing branch to branch from.

    Returns:
        A dict with "ref" and "sha".
    """
    r = gh.get_repo(repo)
    src = r.get_branch(from_branch)
    git_ref = r.create_git_ref(ref=f"refs/heads/{new_branch}", sha=src.commit.sha)
    return {"ref": git_ref.ref, "sha": src.commit.sha}


@mcp.tool
def delete_branch(repo: str, branch: str) -> dict:
    """Delete a branch.

    Refuses to delete the repository's default branch — a hard rule
    with no override, not a confirmation step.

    Args:
        repo: Repository identifier in "owner/name" format.
        branch: Branch to delete.

    Returns:
        A dict with "deleted": true.
    """
    r = gh.get_repo(repo)
    _guard_not_default_branch(r, branch, "delete")
    ref = r.get_git_ref(f"heads/{branch}")
    ref.delete()
    return {"deleted": True}


@mcp.tool
def force_update_branch(repo: str, branch: str, sha: str) -> dict:
    """Force a branch to point at a specific commit, discarding any
    commits currently on it that aren't ancestors of that commit —
    the GitHub API equivalent of `git push --force`.

    Refuses to target the repository's default branch — a hard rule
    with no override, not a confirmation step, since this is exactly
    the kind of operation a prompt-injected instruction hidden in repo
    content could try to abuse.

    Args:
        repo: Repository identifier in "owner/name" format.
        branch: Branch to force-update. Cannot be the default branch.
        sha: Commit SHA the branch should point to afterward.

    Returns:
        A dict with "ref" and "sha".
    """
    r = gh.get_repo(repo)
    _guard_not_default_branch(r, branch, "force-update")
    ref = r.get_git_ref(f"heads/{branch}")
    ref.edit(sha=sha, force=True)
    return {"ref": ref.ref, "sha": sha}


# =====================================================================
# Pull requests
# =====================================================================

@mcp.tool
def create_pull_request(repo: str, branch: str, base: str, title: str, body: str) -> dict:
    """Open a pull request.

    Args:
        repo: Repository identifier in "owner/name" format.
        branch: Head branch containing the changes.
        base: Base branch the changes should merge into.
        title: Pull request title.
        body: Pull request description (Markdown supported).

    Returns:
        A dict with "number" and "html_url".
    """
    r = gh.get_repo(repo)
    pr = r.create_pull(title=title, body=body, head=branch, base=base)
    return {"number": pr.number, "html_url": pr.html_url}


@mcp.tool
def list_pull_requests(repo: str, state: str = "open", limit: int = 20) -> list[dict]:
    """List pull requests, most recently created first.

    Args:
        repo: Repository identifier in "owner/name" format.
        state: One of "open", "closed", or "all".
        limit: Maximum number of pull requests to return.

    Returns:
        A list of dicts with "number", "title", "state", "draft",
        "head" (source branch), "base" (target branch), and "html_url".
    """
    r = gh.get_repo(repo)
    prs = r.get_pulls(state=state, sort="created", direction="desc")
    return [
        {
            "number": p.number,
            "title": p.title,
            "state": p.state,
            "draft": p.draft,
            "head": p.head.ref,
            "base": p.base.ref,
            "html_url": p.html_url,
        }
        for p in prs[:limit]
    ]


@mcp.tool
def get_pull_request(repo: str, number: int) -> dict:
    """Get full details of a single pull request.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Pull request number.

    Returns:
        A dict with "title", "body", "state", "draft", "mergeable"
        (true/false/null — null means GitHub hasn't finished computing
        it yet, retry shortly), "head", "base", "additions",
        "deletions", "changed_files", and "html_url".
    """
    r = gh.get_repo(repo)
    p = r.get_pull(number)
    return {
        "title": p.title,
        "body": p.body,
        "state": p.state,
        "draft": p.draft,
        "mergeable": p.mergeable,
        "head": p.head.ref,
        "base": p.base.ref,
        "additions": p.additions,
        "deletions": p.deletions,
        "changed_files": p.changed_files,
        "html_url": p.html_url,
    }


@mcp.tool
def list_pull_request_files(repo: str, number: int) -> list[dict]:
    """List the files changed in a pull request, with their diffs.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Pull request number.

    Returns:
        A list of dicts with "filename", "status" ("added", "modified",
        "removed", or "renamed"), "additions", "deletions", and
        "patch" (unified diff for that file, if GitHub provides one).
    """
    r = gh.get_repo(repo)
    p = r.get_pull(number)
    return [
        {
            "filename": f.filename,
            "status": f.status,
            "additions": f.additions,
            "deletions": f.deletions,
            "patch": getattr(f, "patch", None),
        }
        for f in p.get_files()
    ]


@mcp.tool
def merge_pull_request(repo: str, number: int, merge_method: str = "merge") -> dict:
    """Merge a pull request.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Pull request number.
        merge_method: One of "merge" (merge commit), "squash" (squash
            and merge), or "rebase" (rebase and merge).

    Returns:
        A dict with "merged" (bool) and "sha" (the resulting commit, if merged).
    """
    r = gh.get_repo(repo)
    p = r.get_pull(number)
    status = p.merge(merge_method=merge_method)
    return {"merged": status.merged, "sha": status.sha}


@mcp.tool
def add_pull_request_comment(repo: str, number: int, body: str) -> dict:
    """Add a comment to a pull request's conversation.

    This adds a general conversation comment, not a review comment
    tied to a specific line of a diff.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Pull request number.
        body: Comment text (Markdown supported).

    Returns:
        A dict with "html_url".
    """
    comment = gh.get_repo(repo).get_issue(number).create_comment(body)
    return {"html_url": comment.html_url}


# =====================================================================
# Issues
# =====================================================================

@mcp.tool
def list_issues(repo: str, state: str = "open", limit: int = 20) -> list[dict]:
    """List issues. Pull requests are excluded, even though GitHub's
    API technically models every PR as an issue too.

    Args:
        repo: Repository identifier in "owner/name" format.
        state: One of "open", "closed", or "all".
        limit: Maximum number of issues to return.

    Returns:
        A list of dicts with "number", "title", "state", "html_url".
    """
    r = gh.get_repo(repo)
    result = []
    for issue in r.get_issues(state=state):
        if issue.pull_request is not None:
            continue
        result.append({
            "number": issue.number,
            "title": issue.title,
            "state": issue.state,
            "html_url": issue.html_url,
        })
        if len(result) >= limit:
            break
    return result


@mcp.tool
def get_issue(repo: str, number: int) -> dict:
    """Get full details of a single issue.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Issue number.

    Returns:
        A dict with "title", "body", "state", "labels" (list of strings), "html_url".
    """
    issue = gh.get_repo(repo).get_issue(number)
    return {
        "title": issue.title,
        "body": issue.body,
        "state": issue.state,
        "labels": [label.name for label in issue.labels],
        "html_url": issue.html_url,
    }


@mcp.tool
def create_issue(repo: str, title: str, body: str = "", labels: list[str] | None = None) -> dict:
    """Open a new issue.

    Args:
        repo: Repository identifier in "owner/name" format.
        title: Issue title.
        body: Issue description (Markdown supported).
        labels: Label names to apply. Labels that don't already exist
            on the repository are silently skipped by GitHub's API.

    Returns:
        A dict with "number" and "html_url".
    """
    r = gh.get_repo(repo)
    issue = r.create_issue(title=title, body=body, labels=labels or [])
    return {"number": issue.number, "html_url": issue.html_url}


@mcp.tool
def add_issue_comment(repo: str, number: int, body: str) -> dict:
    """Add a comment to an issue.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Issue number.
        body: Comment text (Markdown supported).

    Returns:
        A dict with "html_url".
    """
    comment = gh.get_repo(repo).get_issue(number).create_comment(body)
    return {"html_url": comment.html_url}


@mcp.tool
def close_issue(repo: str, number: int) -> dict:
    """Close an issue. Fully reversible: reopening it in GitHub's UI
    restores it exactly as it was.

    Args:
        repo: Repository identifier in "owner/name" format.
        number: Issue number.

    Returns:
        A dict with "state": "closed".
    """
    issue = gh.get_repo(repo).get_issue(number)
    issue.edit(state="closed")
    return {"state": "closed"}


# =====================================================================
# Repository creation
# =====================================================================

@mcp.tool
def create_repository(name: str, description: str = "", private: bool = True) -> dict:
    """Create a new repository under the token's account.

    Note: this needs broader "Administration" permission than every
    other tool here. If your GitHub token is a fine-grained PAT scoped
    to specific existing repos only, this call will fail with a
    permissions error — it needs account-level repo-creation rights.

    Args:
        name: Repository name.
        description: Short repository description.
        private: Whether the new repository is private. Defaults to
            true so nothing is made public by accident.

    Returns:
        A dict with "full_name" and "html_url".
    """
    r = gh.get_user().create_repo(name=name, description=description, private=private)
    return {"full_name": r.full_name, "html_url": r.html_url}


# Deliberately excluded: deleting a repository. Unlike everything
# above, that's not a "basic developer tool" a coding agent needs day
# to day, it cascades (issues, PRs, wiki, releases, stars, and fork
# links all go with it), and GitHub gives no undo. If you ever want a
# repo gone, do that one by hand in GitHub's UI.
#
# Also excluded, as a different API surface than "work with my code":
# GitHub Actions/workflows, releases/tags, and collaborator/permission
# management. Say the word if any of those would actually help.


# =====================================================================
# Vercel — environment variables & redeploys
#
# The official Vercel connector has no way to read or write
# environment variables at all, and no tool to redeploy an existing
# git-linked project's latest commit (only a fresh git import, or a
# raw file upload that bypasses git entirely). These four tools exist
# to fill exactly that gap — nothing else. Everything else about a
# Vercel project (listing projects, deployment status, logs, domains)
# already works fine through the official connector, so it isn't
# duplicated here.
# =====================================================================

@mcp.tool
def vercel_list_env_vars(project: str, target: str = "") -> list[dict]:
    """List a Vercel project's environment variables.

    Values are never returned by this tool, even for the "plain" type
    where Vercel's API would technically allow it — this is metadata
    only, by design, so secret values don't end up sitting in chat
    history just from asking "what variables exist."

    Args:
        project: Vercel project ID or name.
        target: If set, only variables scoped to this environment are
            returned. One of "production", "preview", or "development".

    Returns:
        A list of dicts with "id", "key", "target" (list of
        environments it applies to), "type" ("plain", "encrypted", or
        "sensitive"), and "updated_at" (Unix ms, or null).
    """
    data = _vercel_request("GET", f"/v10/projects/{project}/env")
    envs = data.get("envs") if isinstance(data, dict) else data
    result = [
        {
            "id": e["id"],
            "key": e["key"],
            "target": e.get("target", []),
            "type": e.get("type"),
            "updated_at": e.get("updatedAt"),
        }
        for e in (envs or [])
    ]
    if target:
        result = [e for e in result if target in e["target"]]
    return result


@mcp.tool
def vercel_set_env_var(
    project: str,
    key: str,
    value: str,
    target: list[str] | None = None,
    sensitive: bool = True,
) -> dict:
    """Create or update an environment variable on a Vercel project.

    Creates it if the key doesn't already exist for the given target
    environments, otherwise updates it — one call either way. Doesn't
    redeploy anything: per Vercel's own behavior, a new or changed
    value only takes effect on the *next* deployment, existing
    deployments keep what they were built with. Call vercel_redeploy
    afterward if you need it live now.

    Args:
        project: Vercel project ID or name.
        key: Environment variable name.
        value: The value to set.
        target: Which environments this applies to. Defaults to all
            three: ["production", "preview", "development"].
        sensitive: If true (the default), the value can never be read
            back through the dashboard, CLI, or this adapter again
            after this call — it's still usable at build/runtime, just
            never retrievable. This is Vercel's own recommended
            default for anything secret-shaped; set false only if you
            specifically need to read the value back later (Vercel
            calls that type "encrypted" instead).

    Returns:
        A dict with "key", "target", and "type".
    """
    body = {
        "key": key,
        "value": value,
        "type": "sensitive" if sensitive else "encrypted",
        "target": target or ["production", "preview", "development"],
    }
    data = _vercel_request(
        "POST", f"/v10/projects/{project}/env",
        params={"upsert": "true"}, json=body,
    )
    created = data.get("created", data) if isinstance(data, dict) else {}
    return {
        "key": created.get("key", key),
        "target": created.get("target", body["target"]),
        "type": created.get("type", body["type"]),
    }


@mcp.tool
def vercel_remove_env_var(project: str, key: str, target: str = "") -> dict:
    """Delete an environment variable from a Vercel project.

    Args:
        project: Vercel project ID or name.
        key: Environment variable name to remove.
        target: If set, only removes the entry scoped to this one
            environment ("production", "preview", or "development").
            If omitted, removes every entry for this key across every
            environment it's set in — use vercel_list_env_vars first
            if you're not sure that's what you want.

    Returns:
        A dict with "removed": a list of the environment lists that
        were deleted, e.g. [["production"]] or [["preview", "development"]].
    """
    data = _vercel_request("GET", f"/v10/projects/{project}/env")
    envs = data.get("envs") if isinstance(data, dict) else data
    matches = [e for e in (envs or []) if e["key"] == key]
    if target:
        matches = [e for e in matches if target in e.get("target", [])]
    if not matches:
        raise ValueError(
            f"No env var '{key}' found on '{project}'"
            + (f" for target '{target}'" if target else "")
        )
    removed = []
    for e in matches:
        _vercel_request("DELETE", f"/v9/projects/{project}/env/{e['id']}")
        removed.append(e.get("target", []))
    return {"removed": removed}


@mcp.tool
def vercel_redeploy(project: str, branch: str = "", target: str = "production") -> dict:
    """Trigger a new deployment for a Vercel project from its linked
    GitHub repo's latest commit — the same effect as pushing a new
    commit, not a raw file upload.

    Args:
        project: Vercel project ID or name. Must already be linked to
            a GitHub repo in Vercel (true for anything imported from
            GitHub, which is how Vercel projects normally get created).
        branch: Branch to deploy. Defaults to that repo's default
            branch on GitHub.
        target: One of "production" or "preview".

    Returns:
        A dict with "id" (deployment ID), "url", and "ready_state".
    """
    proj = _vercel_request("GET", f"/v9/projects/{project}")
    link = proj.get("link") or {}
    if link.get("type") != "github":
        raise ValueError(
            f"'{project}' isn't linked to a GitHub repo in Vercel (link type: "
            f"{link.get('type') or 'none'}) — this tool only redeploys "
            f"git-linked projects."
        )
    org, repo = link.get("org"), link.get("repo")
    ref = branch or gh.get_repo(f"{org}/{repo}").default_branch
    body = {
        "name": proj.get("name", project),
        "target": target,
        "gitSource": {"type": "github", "org": org, "repo": repo, "ref": ref},
    }
    data = _vercel_request("POST", "/v13/deployments", json=body)
    return {"id": data.get("id"), "url": data.get("url"), "ready_state": data.get("readyState")}


# Deliberately not included: deleting a project, and buying or
# attaching domains. Both already go through Vercel's own official
# connector, which gates domain purchases behind an explicit
# cost-confirmation step (get_purchase_quote / confirm_cost) — no
# reason to build a second path around that here.


# =====================================================================
# Supabase — Edge Function secrets
#
# The official Supabase connector has no way to set or read Edge
# Function secrets, and deliberately never exposes the service_role
# key. This fills the secrets gap and stops there — the service_role
# key stays out on purpose: it's a standing credential that bypasses
# Row Level Security entirely, so leaking it into a chat transcript is
# a bigger, longer-lived exposure than any single bad call. Ordinary
# database work (queries, migrations) already goes through the
# official connector's execute_sql / apply_migration tools.
# =====================================================================

@mcp.tool
def supabase_list_secrets(project_ref: str) -> list[dict]:
    """List the names of a Supabase project's Edge Function secrets.

    Values are never returned — Supabase's own API may redact them
    anyway, but this tool strips the field regardless, so a routine
    "what secrets exist" call can never surface a value.

    Args:
        project_ref: Supabase project reference ID (e.g. "abcdefghij").

    Returns:
        A list of dicts with "name" and "updated_at" (if provided).
    """
    data = _supabase_mgmt_request("GET", f"/v1/projects/{project_ref}/secrets")
    items = data if isinstance(data, list) else data.get("secrets", [])
    return [{"name": s.get("name"), "updated_at": s.get("updated_at")} for s in items]


@mcp.tool
def supabase_set_secrets(project_ref: str, secrets: dict[str, str]) -> dict:
    """Create or update one or more Edge Function secrets in a single call.

    Args:
        project_ref: Supabase project reference ID.
        secrets: Mapping of secret name to value, e.g.
            {"STRIPE_SECRET_KEY": "sk_live_..."}. Names can't start
            with "SUPABASE_" — that prefix is reserved for values
            Supabase injects into every function automatically.

    Returns:
        A dict with "set": the list of secret names written.
    """
    reserved = [k for k in secrets if k.startswith("SUPABASE_")]
    if reserved:
        raise ValueError(
            f"Refusing to set {reserved}: names starting with 'SUPABASE_' are "
            f"reserved for values Supabase injects itself and can't be "
            f"overridden via the API."
        )
    body = [{"name": k, "value": v} for k, v in secrets.items()]
    _supabase_mgmt_request("POST", f"/v1/projects/{project_ref}/secrets", json=body)
    return {"set": list(secrets.keys())}


@mcp.tool
def supabase_delete_secrets(project_ref: str, names: list[str]) -> dict:
    """Delete one or more Edge Function secrets by name.

    Uses Supabase's bulk-delete endpoint, which Supabase's own docs
    currently flag as experimental and subject to change.

    Args:
        project_ref: Supabase project reference ID.
        names: Secret names to delete.

    Returns:
        A dict with "deleted": the list of names requested.
    """
    _supabase_mgmt_request("DELETE", f"/v1/projects/{project_ref}/secrets", json=names)
    return {"deleted": names}


# Deliberately not included: retrieving the service_role/secret key
# (never exposed via the official connector either, and for good
# reason — see the section note above) and deleting a project
# (irreversible, cascades, not a routine action — same reasoning as
# excluding repo deletion above).


# ---- Auth pages (public, unauthenticated routes) -------------------------
# Supabase's OAuth Server redirects the browser to /oauth/consent
# mid-flow. These are plain HTTP routes, separate from the MCP
# protocol endpoint and from SupabaseProvider's bearer-token check.

@mcp.custom_route("/healthz", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/auth-config", methods=["GET"])
async def auth_config(request: Request) -> JSONResponse:
    # Safe to expose: the anon/publishable key is designed to be public.
    return JSONResponse({"supabaseUrl": SUPABASE_URL, "supabaseAnonKey": SUPABASE_ANON_KEY})


@mcp.custom_route("/login", methods=["GET"])
async def login_page(request: Request) -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "login.html").read_text())


@mcp.custom_route("/oauth/consent", methods=["GET"])
async def consent_page(request: Request) -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "consent.html").read_text())


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=PORT)
