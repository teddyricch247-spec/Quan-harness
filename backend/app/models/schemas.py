from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Auth (§4, §28)
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str


class AccountDeleteRequest(BaseModel):
    confirmation: str  # must equal "DELETE" — enforced in the router


# ---------------------------------------------------------------------------
# LLM credentials (§7, §10.1)
# ---------------------------------------------------------------------------

LlmProvider = Literal["anthropic", "openai", "google", "openrouter", "custom"]


class LlmCredentialCreate(BaseModel):
    label: str
    provider: LlmProvider
    model: str
    api_key: str
    base_url: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False


class LlmCredentialUpdate(BaseModel):
    label: str | None = None
    model: str | None = None
    api_key: str | None = None  # if provided, rotates the stored secret (§24)
    base_url: str | None = None
    extra_headers: dict[str, str] | None = None


class LlmCredentialOut(BaseModel):
    id: str
    label: str
    provider: str
    model: str
    base_url: str | None
    extra_headers: dict[str, Any]
    is_default: bool
    api_key_last_four: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# GitHub sync credential (§8, §10.1)
# ---------------------------------------------------------------------------


class GithubCredentialManualCreate(BaseModel):
    label: str
    token: str  # fine-grained PAT, entered manually
    is_default: bool = False


class GithubCredentialRotate(BaseModel):
    token: str  # new token value — only valid for credential_type == 'pat'


class GithubCredentialOut(BaseModel):
    id: str
    credential_type: str
    label: str
    github_app_account_login: str | None
    is_default: bool
    token_last_four: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# MCP connectors (§9, §10.1)
# ---------------------------------------------------------------------------

McpAuthMode = Literal["none", "static_token", "oauth"]
PermissionState = Literal["on", "off", "ask"]


class McpServerCreate(BaseModel):
    name: str
    url: str
    auth_mode: McpAuthMode = "none"
    static_token: str | None = None  # required when auth_mode == "static_token"
    default_permission_state: PermissionState = "ask"


class McpServerOut(BaseModel):
    id: str
    name: str
    url: str
    auth_mode: str
    enabled: bool
    default_permission_state: str
    discovered_tools: list[dict]
    last_handshake_at: datetime | None
    last_handshake_error: str | None
    created_at: datetime


class McpToolOverrideUpdate(BaseModel):
    permission_state: PermissionState | None  # null = inherit server default


# ---------------------------------------------------------------------------
# Projects (§10.2, §12, §28)
# ---------------------------------------------------------------------------

ProjectSetupMode = Literal["scratch", "import", "create_new_repo"]


class ProjectCreate(BaseModel):
    name: str
    mode: ProjectSetupMode = "scratch"
    # mode == "import"
    github_repo: str | None = None  # "owner/repo"
    # mode == "create_new_repo"
    new_repo_name: str | None = None
    new_repo_private: bool = True
    # common
    github_credential_id: str | None = None
    llm_credential_id: str | None = None
    connector_ids: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    github_credential_id: str | None = None
    llm_credential_id: str | None = None
    test_command: str | None = None
    max_turn_iterations: int | None = None


class ProjectDeleteRequest(BaseModel):
    confirmation: str  # must equal the project's own name


class ProjectOut(BaseModel):
    id: str
    name: str
    github_repo: str | None
    github_default_branch: str | None
    github_credential_id: str | None
    llm_credential_id: str | None
    test_command: str | None
    max_turn_iterations: int
    workspace_billing_state: str | None
    harness_branch_ready: bool
    created_at: datetime


class ProjectConnectorsAccessUpdate(BaseModel):
    connector_ids: list[str]


# ---------------------------------------------------------------------------
# Sessions (§10.3, §28) — schema/CRUD only in Phase 1, no turn loop yet
# ---------------------------------------------------------------------------


class SessionCreate(BaseModel):
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    project_id: str
    title: str | None
    status: str
    branch_name: str | None
    base_branch: str | None
    pr_url: str | None
    plan: list[dict]
    turn_iteration_count: int
    read_only: bool
    read_only_reason: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Workspace, Push/Pull, Checkpoints (§14.2-§14.3, §23, §25) — Phase 2
# ---------------------------------------------------------------------------


class WorkspaceOut(BaseModel):
    project_id: str
    billing_state: str
    provisioned: bool  # False while sprite_handle is still Phase 1's `pending-*` stub
    last_active_at: datetime | None


class PushRequest(BaseModel):
    repo_name: str | None = None  # only used the first time, if no repo is linked yet
    private: bool = True


class PushResult(BaseModel):
    full_name: str
    branch: str
    commit_sha: str
    pull_request_url: str | None


class PullRequest(BaseModel):
    confirm_discard: bool = False


class PullResult(BaseModel):
    needs_confirmation: bool
    branch: str


class CheckpointOut(BaseModel):
    id: str
    project_id: str
    session_id: str
    git_commit_sha: str
    restorable: bool  # True only if this checkpoint's session is the project's active one
    created_at: datetime


class ProjectSecretCreate(BaseModel):
    name: str
    value: str


class ProjectSecretOut(BaseModel):
    id: str
    name: str
    value_last_four: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Turn loop, system prompt, compaction, stuck detection (§16-§19) — Phase 3
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    text: str


class InterruptCreate(BaseModel):
    text: str


class SessionEventOut(BaseModel):
    id: int
    session_id: str
    parent_event_id: int | None
    role: str
    event_type: str
    content: dict
    created_at: datetime


class ApprovalOut(BaseModel):
    id: str
    session_id: str
    action_type: str
    payload: dict
    status: str
    created_at: datetime
    resolved_at: datetime | None


class ApprovalDecision(BaseModel):
    approved: bool


class TurnStartResult(BaseModel):
    session_id: str
    status: str


# ---------------------------------------------------------------------------
# Memory (§20) — Phase 4.1
# ---------------------------------------------------------------------------


class ProjectMemoryOut(BaseModel):
    project_id: str
    memory_md: str


class ProjectMemoryUpdate(BaseModel):
    memory_md: str


class BuildUserMemoryOut(BaseModel):
    memory_md: str


class BuildUserMemoryUpdate(BaseModel):
    memory_md: str


# ---------------------------------------------------------------------------
# Project Knowledge (§21) — Phase 4.2
# ---------------------------------------------------------------------------

ProjectKnowledgeTriggerType = Literal["keyword", "path"]


class ProjectKnowledgeCreate(BaseModel):
    name: str
    body: str
    trigger_type: ProjectKnowledgeTriggerType
    trigger_value: str


class ProjectKnowledgeUpdate(BaseModel):
    name: str | None = None
    body: str | None = None
    trigger_type: ProjectKnowledgeTriggerType | None = None
    trigger_value: str | None = None


class ProjectKnowledgeOut(BaseModel):
    id: str
    project_id: str
    name: str
    body: str
    trigger_type: str
    trigger_value: str
    created_at: datetime
    updated_at: datetime
