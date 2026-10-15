"""§23.3: 'Push first prompts to create one — name, visibility.' Extracted to a
pure module so the slugification is unit testable without httpx/vault involved.
app/services/git_sync.py imports suggest_repo_name from here."""
import re

_SAFE_REPO_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def suggest_repo_name(project_name: str) -> str:
    slug = _SAFE_REPO_NAME_RE.sub("-", project_name.strip()).strip("-").lower()
    return slug or "quan-harness-project"
