export interface LlmCredential {
  id: string;
  label: string;
  provider: "anthropic" | "openai" | "google" | "openrouter" | "custom";
  model: string;
  base_url: string | null;
  extra_headers: Record<string, string>;
  is_default: boolean;
  api_key_last_four: string;
  created_at: string;
  updated_at: string;
}

export interface GithubCredential {
  id: string;
  credential_type: "pat" | "github_app";
  label: string;
  github_app_account_login: string | null;
  is_default: boolean;
  token_last_four: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpTool {
  name: string;
  description: string;
  permission_state: "on" | "off" | "ask";
}

export interface McpServer {
  id: string;
  name: string;
  url: string;
  auth_mode: "none" | "static_token" | "oauth";
  enabled: boolean;
  default_permission_state: "on" | "off" | "ask";
  discovered_tools: McpTool[];
  // Phase 4.3 — a pre-registered OAuth client id, for a server whose
  // authorization server doesn't support dynamic client registration (e.g.
  // GitHub's own remote MCP server). Not secret — safe to display as-is.
  // Null for a connector using DCR, or one in static_token/none mode.
  oauth_client_id: string | null;
  last_handshake_at: string | null;
  last_handshake_error: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  github_repo: string | null;
  github_default_branch: string | null;
  github_credential_id: string | null;
  llm_credential_id: string | null;
  test_command: string | null;
  max_turn_iterations: number;
  workspace_billing_state: "running" | "warm" | "cold" | null;
  harness_branch_ready: boolean;
  created_at: string;
  // Phase 4.4 — set only on the POST /projects response for mode == "import",
  // and only when the automatic first Pull failed. Undefined/null everywhere
  // else. A non-null value never means project creation itself failed.
  import_pull_error?: string | null;
  // Phase 5.1/5.2/5.5 (§23.5/§23.6) — repo_origin decides whether the
  // monorepo-detection/confirmation step ever runs (see DeployPanel.tsx).
  repo_origin: "scratch" | "imported";
  deploy_targets: DeployTarget[];
  deploy_targets_confirmed: boolean;
}

// Phase 5.1/5.2/5.5 (§23.5/§23.6/§23.9)
export interface DeployTarget {
  name: string;
  root: string;
  stack: "nextjs" | "node" | "python" | "dockerfile" | "llm_fallback" | null;
  build_cmd: string | null;
  run_cmd: string | null;
  port: number | null;
}

export interface DeployTriggerResult {
  status: "running";
}

export interface DeployNeedsConfirmationResult {
  needs_confirmation: true;
  proposed_targets: DeployTarget[];
}

export interface DeployRun {
  id: string;
  project_id: string;
  status: "running" | "success" | "failed";
  target_name: string | null;
  phase: "detect" | "build" | "start" | "healthy";
  stack: string | null;
  build_cmd: string | null;
  run_cmd: string | null;
  port: number | null;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  failure_class: "build" | "environment" | null;
  // Phase 5.4 — which §23.8 limitation an environment failure looks like.
  environment_kind: PreviewKind | null;
  diagnosis_text: string | null;
  suggested_fix_prompt: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Session {
  id: string;
  project_id: string;
  title: string | null;
  status: "idle" | "running" | "waiting_approval" | "completed" | "failed" | "stuck" | "archived";
  branch_name: string | null;
  base_branch: string | null;
  pr_url: string | null;
  plan: { step: string; status: "pending" | "in_progress" | "done" }[]; // §14.10 — Phase 3
  turn_iteration_count: number;
  read_only: boolean;
  read_only_reason: "concurrency_cap" | "checkpoint_restore" | null;
  // Phase 4.5 (§26) — 'user' for every interactively-created session (every
  // session created before this phase is implicitly this, via the backend
  // column's own default); 'scheduled' only for one app/services/scheduler.py
  // started on a ProjectSchedule's behalf. schedule_id is that schedule's id
  // when trigger === 'scheduled', else null.
  trigger: "user" | "scheduled";
  schedule_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Workspace {
  project_id: string;
  billing_state: "running" | "warm" | "cold";
  provisioned: boolean;
  last_active_at: string | null;
}

export interface PushResult {
  full_name: string;
  branch: string;
  commit_sha: string;
  pull_request_url: string | null;
}

export interface PullResult {
  needs_confirmation: boolean;
  branch: string;
}

export interface Checkpoint {
  id: string;
  project_id: string;
  session_id: string;
  git_commit_sha: string;
  restorable: boolean;
  created_at: string;
}

export interface ProjectSecret {
  id: string;
  name: string;
  value_last_four: string;
  created_at: string;
}

export interface AuditLogEntry {
  id: number;
  tool: string;
  action: string;
  success: boolean;
  initiated_by: "agent" | "user" | "system";
  output_summary: string | null;
  project_id: string | null;
  session_id: string | null;
  created_at: string;
}

export interface ProjectMemory {
  project_id: string;
  memory_md: string;
}

export interface BuildUserMemory {
  memory_md: string;
}

export interface ProjectKnowledgeNote {
  id: string;
  project_id: string;
  name: string;
  body: string;
  trigger_type: "keyword" | "path";
  trigger_value: string;
  created_at: string;
  updated_at: string;
}

// Phase 4.5 (§26) — a recurring, opt-in check on a project. See
// docs/PHASE4_5_NOTES.md for the full behavior (forced-Ask on every mutating
// tool call during a run it starts, UTC-only cron, etc).
export interface ProjectSchedule {
  id: string;
  project_id: string;
  description: string; // stands in as the initiating message on every run
  frequency: "hourly" | "daily" | "custom";
  cron_expression: string | null; // set, and only meaningful, when frequency === "custom"; UTC
  enabled: boolean;
  last_run_at: string | null;
  last_session_id: string | null;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Live Preview (§23.7) and known preview limitations (§23.8) — Phase 5.3 / 5.4
// ---------------------------------------------------------------------------

export type PreviewKind = "cors" | "secrets" | "oauth" | "database" | "nested_container" | "other";

export interface PreviewStatus {
  configured: boolean; // does the server have PREVIEW_BASE_DOMAIN + PREVIEW_SIGNING_SECRET
  can_open: boolean;
  unavailable_reason: string | null;
  subdomain: string | null;
  // The stable preview origin — the one address a client allowlists for CORS, once (§23.8).
  origin: string | null;
  // 'running' is the only billed state (§23.7).
  billing_state: "running" | "warm" | "cold" | null;
  entry_target: string | null;
  deployed: boolean;
}

export interface PreviewSession {
  url: string; // single-use, short-lived — load it in the iframe once
  expires_in_seconds: number;
}

export interface PreviewRestartResult {
  results: { target: string; started: boolean; exit_code: number | null; log: string }[];
}

// Name, an optional hint, timestamps. The API never returns a value.
export interface PreviewSecret {
  id: string;
  name: string;
  value_hint: string | null;
  created_at: string;
  updated_at: string;
  created?: boolean | null;
}

export interface GuidanceOption {
  label: string;
  detail: string;
  // A label for a button the PERSON clicks. Never something the harness performs for them (§23.8).
  action: "copy_origin" | "copy_ips" | "open_secrets" | null;
}

export interface Guidance {
  kind: string;
  title: string;
  can_fix: "yes" | "partly" | "no";
  why: string;
  options: GuidanceOption[];
}

export interface PreviewNotification {
  id: string;
  kind: PreviewKind;
  status: "open" | "dismissed" | "resolved";
  source: string;
  title: string;
  body: string;
  detail: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  guidance: Guidance;
}

export interface PreviewLimitations {
  origin: string | null;
  egress_ips: string[];
  guidance: Guidance[];
}
