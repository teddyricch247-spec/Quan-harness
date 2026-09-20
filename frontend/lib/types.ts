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
