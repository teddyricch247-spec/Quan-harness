from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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

# Must match provider_catalog.PROVIDER_IDS and the latest llm_credentials_provider_check
# migration — tests/test_provider_catalog.py fails if any of the three drift.
LlmProvider = Literal[
    "openrouter",
    "anthropic",
    "openai",
    "google",
    "groq",
    "together",
    "fireworks",
    "deepseek",
    "mistral",
    "xai",
    "cerebras",
    "custom",
]


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]


class ReasoningConfig(BaseModel):
    """How a credential's model should think. Stored on llm_credentials.reasoning (jsonb).

    Every field is optional and "unset" means "the model's own default" — nothing is sent
    to the provider for it. So `{}` (all defaults) is the native behaviour, and is what
    resetting to default stores. Which `effort` values a given model really accepts is
    checked against provider_catalog.reasoning_profile in the router, not here.
    """

    effort: ReasoningEffort | None = None  # "none" = thinking off
    max_tokens: int | None = Field(default=None, ge=1024, le=32768)  # a raw thinking budget
    show: bool = True  # False = ask the provider not to return the thinking text

    @model_validator(mode="after")
    def _effort_xor_budget(self):
        if self.effort is not None and self.max_tokens is not None:
            raise ValueError("Set either a thinking level or a token budget, not both.")
        return self

    def to_stored(self) -> dict:
        """Only the non-default keys, so an untouched credential stores exactly `{}`."""
        out: dict = {}
        if self.effort is not None:
            out["effort"] = self.effort
        if self.max_tokens is not None:
            out["max_tokens"] = self.max_tokens
        if not self.show:
            out["show"] = False
        return out


class LlmCredentialCreate(BaseModel):
    label: str
    provider: LlmProvider
    model: str
    api_key: str
    base_url: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    is_default: bool = False
    reasoning: ReasoningConfig | None = None


class LlmCredentialUpdate(BaseModel):
    label: str | None = None
    model: str | None = None
    api_key: str | None = None  # if provided, rotates the stored secret (§24)
    base_url: str | None = None
    extra_headers: dict[str, str] | None = None
    reasoning: ReasoningConfig | None = None  # an all-default object resets to the model's own behaviour


class LlmProbeRequest(BaseModel):
    provider: LlmProvider
    api_key: str
    base_url: str | None = None  # only used (and required) for provider == "custom"


class LlmModelOut(BaseModel):
    id: str
    name: str
    context_length: int | None = None
    supports_tools: bool | None = None  # None = the provider didn't say
    supports_reasoning: bool | None = None  # None = the provider didn't say


class LlmProbeOut(BaseModel):
    # ok | invalid_key | no_model_list | unreachable | bad_request — see provider_probe.py.
    # Only invalid_key/bad_request mean "fix this before connecting"; the rest still
    # allow connecting with a manually typed model ID.
    status: str
    message: str | None = None
    models: list[LlmModelOut] = Field(default_factory=list)


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
    reasoning: dict[str, Any] = Field(default_factory=dict)
    # What this credential's model natively accepts ({"efforts": [...], "supports_budget": bool}),
    # or None when the provider has no thinking controls. Derived, never stored.
    reasoning_options: dict[str, Any] | None = None


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
    # Phase 4.3: a pre-registered OAuth client, for an authorization server that
    # doesn't implement RFC 7591 dynamic client registration — GitHub's own
    # remote MCP server (api.githubcopilot.com/mcp) is the concrete, confirmed
    # example this was added for (see mcp_oauth.py's module docstring and
    # 0008_connector_oauth_client.sql). Only meaningful when auth_mode ==
    # "oauth"; oauth_start prefers this over attempting DCR whenever it's set.
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None  # write-only; only valid alongside oauth_client_id
    default_permission_state: PermissionState = "ask"


class McpServerOut(BaseModel):
    id: str
    name: str
    url: str
    auth_mode: str
    enabled: bool
    default_permission_state: str
    discovered_tools: list[dict]
    oauth_client_id: str | None  # not secret — a client_id is a public identifier, safe to display
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
    # Phase 4.4: set only on the POST /projects response for mode == "import",
    # and only when the automatic first Pull (see routers/projects.py's
    # create_project) failed — e.g. the workspace couldn't be provisioned yet
    # because Sprites/Fly credentials aren't configured. None everywhere else
    # (every other endpoint returning ProjectOut has nothing to report here).
    # A non-null value here never means project creation itself failed — the
    # project, its GitHub link, and its credential selection are all real;
    # only the initial pull needs retrying, from the Workspace panel's own
    # Pull button.
    import_pull_error: str | None = None
    # Phase 5.1/5.2/5.5 (§23.5/§23.6) — repo_origin decides whether the
    # monorepo-detection/confirmation step ever runs for this project at
    # all (see db/migrations/0010_deploy_pipeline.sql and
    # app/services/deploy_pipeline.py). deploy_targets is the confirmed (or,
    # while deploy_targets_confirmed is False, merely proposed) shape the
    # frontend's deploy/confirm UI reads and posts back to
    # POST /projects/{id}/deploy/targets.
    repo_origin: str
    deploy_targets: list[dict]
    deploy_targets_confirmed: bool


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
    # Phase 4.5 (§26): 'user' for every interactively-created session (every
    # session created before this phase is implicitly this, via the column's
    # own DB default); 'scheduled' only for one app/services/scheduler.py
    # created on a project_schedules row's behalf. schedule_id is that row's
    # id when trigger == 'scheduled', else None.
    trigger: str
    schedule_id: str | None
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


# ---------------------------------------------------------------------------
# Scheduling / Proactive Scanning (§26) — Phase 4.5
# ---------------------------------------------------------------------------

ScheduleFrequency = Literal["hourly", "daily", "custom"]


class ProjectScheduleCreate(BaseModel):
    description: str  # stands in as the initiating user message on every run (§16.1)
    frequency: ScheduleFrequency
    cron_expression: str | None = None  # required, and only meaningful, when frequency == "custom"
    enabled: bool = True


class ProjectScheduleUpdate(BaseModel):
    description: str | None = None
    frequency: ScheduleFrequency | None = None
    cron_expression: str | None = None
    enabled: bool | None = None


class ProjectScheduleOut(BaseModel):
    id: str
    project_id: str
    description: str
    frequency: str
    cron_expression: str | None
    enabled: bool
    last_run_at: datetime | None
    last_session_id: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Deploy pipeline (§23.5, §23.6, §23.9) — Phase 5.1/5.2/5.5
# ---------------------------------------------------------------------------


class DeployTarget(BaseModel):
    """One entry of projects.deploy_targets — the confirmed (or, before
    confirmation, merely proposed) shape of one deployable root. stack/
    build_cmd/run_cmd/port are None until §23.5's detection has resolved
    them at least once for this target."""

    name: str
    root: str
    stack: str | None = None
    build_cmd: str | None = None
    run_cmd: str | None = None
    port: int | None = None


class DeployTargetsConfirmRequest(BaseModel):
    """§23.6: the person's own confirmation of a proposed (or edited) set of
    deploy targets. Only name/root are accepted from the person — stack/
    build_cmd/run_cmd/port are always re-detected on the next deploy (see
    deploy_pipeline.confirm_targets's own docstring for why)."""

    targets: list[dict] = Field(..., min_length=1)


class DeployTriggerRequest(BaseModel):
    # §23.6 — re-runs root detection (for an 'imported' project) or clears a
    # 'scratch' project's single resolved target, forcing §23.5's detection
    # to run again from scratch on this deploy, in case the repository's
    # actual structure or stack has changed since it was last resolved.
    force_redetect: bool = False


class DeployTriggerResult(BaseModel):
    status: str  # 'running' — a 202-style "started" response, no run ids yet (a monorepo starts several at once)


class DeployNeedsConfirmationResult(BaseModel):
    """The response (HTTP 200, not an error status) §23.6's monorepo detection returns instead of
    starting a deploy — same "needs_confirmation" shape PullResult already
    established for the same reason (an action that can't proceed without
    the person's own input isn't a plain error)."""

    needs_confirmation: bool = True
    proposed_targets: list[DeployTarget]


class DeployRunOut(BaseModel):
    id: str
    project_id: str
    status: str  # 'running' | 'success' | 'failed'
    target_name: str | None
    phase: str  # 'detect' | 'build' | 'start' | 'healthy'
    stack: str | None
    build_cmd: str | None
    run_cmd: str | None
    port: int | None
    exit_code: int | None
    stdout: str
    stderr: str
    failure_class: str | None
    environment_kind: str | None = None  # Phase 5.3/5.4 — which §23.8 limitation an environment failure looks like
    diagnosis_text: str | None
    suggested_fix_prompt: str | None
    created_at: datetime
    completed_at: datetime | None


# ---------------------------------------------------------------------------
# Live Preview (§23.7) and known preview limitations (§23.8) — Phase 5.3 / 5.4
# ---------------------------------------------------------------------------


class PreviewStatusOut(BaseModel):
    configured: bool  # does this server have PREVIEW_BASE_DOMAIN + PREVIEW_SIGNING_SECRET
    can_open: bool  # configured AND something has been deployed
    unavailable_reason: str | None
    subdomain: str | None
    origin: str | None  # the stable preview origin — the one thing a client allowlists for CORS (§23.8)
    billing_state: Literal["running", "warm", "cold"] | None
    entry_target: str | None
    deployed: bool
    # Deliberately NOT here, and not anywhere in any response: the Sprite's own URL (§23.7).


class PreviewSessionOut(BaseModel):
    url: str  # single-use, short-lived; loads in the iframe, sets the session cookie, redirects home
    expires_in_seconds: int


class PreviewRestartTargetResult(BaseModel):
    target: str
    started: bool
    exit_code: int | None
    log: str


class PreviewRestartOut(BaseModel):
    results: list[PreviewRestartTargetResult]


class PreviewSecretUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)


class PreviewSecretOut(BaseModel):
    """Name, an optional hint, timestamps. NEVER the value — and the hint is only
    present for values long enough that four characters aren't most of the secret."""

    id: str
    name: str
    value_hint: str | None
    created_at: datetime
    updated_at: datetime
    created: bool | None = None  # only set on PUT: true = new, false = replaced


class GuidanceOption(BaseModel):
    label: str
    detail: str
    # A UI hint for a button the PERSON clicks (open the Secrets panel, copy the
    # origin). Never something the harness performs on their behalf — §23.8.
    action: Literal["copy_origin", "copy_ips", "open_secrets"] | None = None


class GuidanceOut(BaseModel):
    kind: str
    title: str
    can_fix: Literal["yes", "partly", "no"]
    why: str
    options: list[GuidanceOption]


class PreviewNotificationOut(BaseModel):
    id: str
    kind: str
    status: Literal["open", "dismissed", "resolved"]
    source: str
    title: str
    body: str
    detail: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    guidance: GuidanceOut


class PreviewLimitationsOut(BaseModel):
    origin: str | None
    egress_ips: list[str]
    guidance: list[GuidanceOut]
