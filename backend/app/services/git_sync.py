"""
§23.3 / §25: Push and Pull, the *only* path between a project's workspace and
GitHub, both strictly user-triggered (§14.5: "there is no github_commit_and_push
tool and never has been... pushing or pulling ... never a tool at all"). Nothing
in this module is reachable from file_tools.py, shell_tools.py, or checkpoints.py
— it is only ever called from app/routers/workspace.py's push/pull endpoints,
which is what makes "zero agent-facing surface of any kind" (implementation
order step 7) true structurally, not just by convention.

This is also the *only* module in the whole Phase 2 surface that ever holds a
GitHub write credential in memory — see §23.2's table. The credential is used to
build a single `http.extraHeader` git-config value passed as one CLI argument
per git-over-HTTPS call and never written to the workspace's own .git/config,
so it never lingers anywhere execute_bash's heuristic guard would otherwise have
to worry about it leaking from (see workspace's own git config after a Push:
`git remote -v` shows a bare https://github.com/... URL with no embedded
credential, same as a token-less clone would).
"""
import base64

from app.repositories import audit as audit_repo
from app.repositories import github_credentials as github_credentials_repo
from app.repositories import projects as projects_repo
from app.services import github_oauth, vault, workspace_service
from app.services.repo_naming import suggest_repo_name
from app.services.workspace_paths import REPO_ROOT

HARNESS_BRANCH = "harness/workspace"


class GitSyncError(ValueError):
    pass


async def _resolve_token(user_id: str, project: dict) -> str:
    credential_id = project.get("github_credential_id")
    if credential_id:
        credential = await github_credentials_repo.get_for_user(user_id, credential_id)
    else:
        credentials = await github_credentials_repo.list_for_user(user_id)
        credential = next((c for c in credentials if c["is_default"]), None)
    if credential is None:
        raise GitSyncError(
            "No GitHub credential is connected for this project — connect one under Connections first."
        )
    if credential.get("credential_type") == "github_app":
        # Schema-anticipated (0002_connections.sql), but nothing in Phase 1's
        # Connections flow actually issues a 'github_app' credential yet — a
        # real GitHub App installation-token exchange is separate, unbuilt
        # work. Fail with an accurate message rather than the generic
        # "could not be read" below, which would wrongly suggest reconnecting
        # a PAT would fix it.
        raise GitSyncError(
            "This project's GitHub credential is a GitHub App installation — Push/Pull "
            "only supports personal access token (PAT) credentials right now."
        )
    if not credential.get("token_ref"):
        raise GitSyncError(
            "No GitHub credential is connected for this project — connect one under Connections first."
        )
    token = await vault.read_secret(credential["token_ref"])
    if not token:
        raise GitSyncError("The connected GitHub credential could not be read — try reconnecting it.")
    return token


def _auth_header_config(token: str) -> str:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"http.extraHeader=AUTHORIZATION: basic {basic}"


async def _git(project_id: str, argv: list[str], timeout: int = 60):
    return await workspace_service.exec_in_workspace(project_id, ["git", "-C", REPO_ROOT, *argv], timeout=timeout)


async def push(user_id: str, project_id: str, repo_name: str | None, private: bool) -> dict:
    project = await projects_repo.get_for_user(user_id, project_id)
    if project is None:
        raise GitSyncError("Project not found.")
    token = await _resolve_token(user_id, project)

    created_repo = False
    if not project.get("github_repo"):
        # §23.3: "If the workspace has no linked repo yet, Push first prompts to
        # create one — name, visibility — using the connected GitHub credential,
        # then pushes into it."
        name = repo_name or suggest_repo_name(project["name"])
        created = await github_oauth.create_repository(token, name, private=private)
        project = await projects_repo.update_for_user(
            user_id,
            project_id,
            {"github_repo": created["full_name"], "github_default_branch": created["default_branch"]},
        )
        created_repo = True

    full_name = project["github_repo"]
    default_branch = project.get("github_default_branch") or "main"
    remote_url = f"https://github.com/{full_name}.git"
    auth_config = _auth_header_config(token)

    await _git(project_id, ["remote", "remove", "origin"])  # ignore failure if it doesn't exist yet
    await _git(project_id, ["remote", "add", "origin", remote_url])

    local_head = (await _git(project_id, ["rev-parse", "HEAD"])).stdout.strip()
    tree = (await _git(project_id, ["rev-parse", f"{local_head}^{{tree}}"])).stdout.strip()

    remote_ref = await _git(
        project_id, ["-c", auth_config, "ls-remote", "origin", f"refs/heads/{HARNESS_BRANCH}"]
    )
    remote_sha = remote_ref.stdout.split()[0] if remote_ref.stdout.strip() else None

    # §23.4: "squash the local checkpoint-commit chain into whatever commit(s)
    # actually get pushed to GitHub" — one clean commit per Push, chained onto
    # whatever was pushed last time (a real fast-forward, not a force-push),
    # or rootless if this is the first Push to the branch.
    commit_argv = ["commit-tree", tree, "-m", "Workspace sync"]
    if remote_sha:
        commit_argv += ["-p", remote_sha]
    squash_commit = (await _git(project_id, commit_argv)).stdout.strip()

    push_result = await _git(
        project_id,
        ["-c", auth_config, "push", "origin", f"{squash_commit}:refs/heads/{HARNESS_BRANCH}"],
        timeout=120,
    )
    if push_result.exit_code != 0:
        raise GitSyncError(f"Push failed: {push_result.stderr.strip() or push_result.stdout.strip()}")

    if not project.get("harness_branch_ready"):
        await projects_repo.set_harness_branch_ready(project_id)

    pr = await github_oauth.find_open_pull_request(token, full_name, HARNESS_BRANCH)
    if pr is None and not created_repo:
        # A brand-new empty repo has no default-branch commit yet to open a PR
        # against — GitHub rejects a PR whose base has no history in common.
        # The PR opens on the *next* Push once the default branch has content
        # (e.g. after the person merges this once, or adds a README on GitHub).
        try:
            pr = await github_oauth.create_pull_request(
                token, full_name, HARNESS_BRANCH, default_branch, title="Quan Harness workspace sync"
            )
        except ValueError:
            pr = None

    await audit_repo.record(
        user_id, "push", "push", True, project_id=project_id,
        output_summary=f"{full_name}@{HARNESS_BRANCH}", initiated_by="user",
    )
    return {"full_name": full_name, "branch": HARNESS_BRANCH, "commit_sha": squash_commit, "pull_request_url": pr["html_url"] if pr else None}


async def has_undiscarded_local_changes(project_id: str, pull_branch: str) -> bool:
    status = await _git(project_id, ["status", "--porcelain"])
    if status.stdout.strip():
        return True
    remote_ref = await _git(project_id, ["rev-parse", f"refs/remotes/origin/{pull_branch}"])
    if remote_ref.exit_code != 0:
        return False  # nothing to compare against yet — first pull
    local_head = (await _git(project_id, ["rev-parse", "HEAD"])).stdout.strip()
    return local_head != remote_ref.stdout.strip()


async def pull(user_id: str, project_id: str, confirm_discard: bool) -> dict:
    project = await projects_repo.get_for_user(user_id, project_id)
    if project is None:
        raise GitSyncError("Project not found.")
    if not project.get("github_repo"):
        raise GitSyncError("This project has no linked repository yet — nothing to pull.")
    token = await _resolve_token(user_id, project)

    pull_branch = HARNESS_BRANCH if project.get("harness_branch_ready") else (project.get("github_default_branch") or "main")
    remote_url = f"https://github.com/{project['github_repo']}.git"
    auth_config = _auth_header_config(token)

    await _git(project_id, ["remote", "remove", "origin"])
    await _git(project_id, ["remote", "add", "origin", remote_url])
    fetch = await _git(project_id, ["-c", auth_config, "fetch", "origin", pull_branch], timeout=120)
    if fetch.exit_code != 0:
        raise GitSyncError(f"Pull failed: {fetch.stderr.strip() or fetch.stdout.strip()}")

    if not confirm_discard and await has_undiscarded_local_changes(project_id, pull_branch):
        return {"needs_confirmation": True, "branch": pull_branch}

    # §23.3: "Pull is a full overwrite: the workspace is made to match GitHub
    # exactly, discarding any un-pushed local changes."
    reset = await _git(project_id, ["reset", "--hard", "FETCH_HEAD"])
    if reset.exit_code != 0:
        raise GitSyncError(f"Pull failed during reset: {reset.stderr.strip()}")

    await audit_repo.record(
        user_id, "pull", "pull", True, project_id=project_id,
        output_summary=f"{project['github_repo']}@{pull_branch}", initiated_by="user",
    )
    return {"needs_confirmation": False, "branch": pull_branch}
