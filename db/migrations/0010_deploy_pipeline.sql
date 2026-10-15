-- 0010_deploy_pipeline.sql
-- Quan Harness — Phase 5.1/5.2/5.5 — §23.5 (stack detection & build), §23.6
-- (repo structure edge cases / monorepo), §23.9 (deploy failure handling).
--
-- Everything Phase 2 needed already exists: project_workspaces (0004),
-- exec_in_workspace (app/services/workspace_service.py). This migration adds
-- exactly the two pieces this sub-prompt's own scope depends on that weren't
-- anticipated by earlier schema:
--
--   1. deploy_runs — one row per attempted build+start, holding the raw
--      stdout/stderr/exit code (§23.9 point 1, "captures raw stdout/stderr/
--      exit code ... and displays it immediately") plus, once produced, the
--      tool-less diagnosis and suggested-fix text (§23.9 point 2). Not a new
--      idea bolted onto `projects` — `projects.deploy_targets` (0004) already
--      holds the *confirmed, persistent* shape of a project's deploy targets;
--      this table holds the *history* of attempts against that shape, the
--      same relationship checkpoints (0005) has to a project's workspace.
--   2. `projects.repo_origin` / `projects.deploy_targets_confirmed` — §23.6's
--      monorepo detection/confirmation step is explicitly scoped to "imported
--      repos only ... a codebase the harness didn't build and doesn't already
--      know the shape of," and explicitly NOT needed for a from-scratch
--      project ("the system already knows the roots because it's the one
--      that created them"). Nothing on `projects` currently records which of
--      §12's three setup modes a project was created under, once creation
--      itself finishes — `repo_origin` is that record, collapsed to the one
--      distinction §23.6 actually cares about: 'imported' (mode == 'import')
--      vs. 'scratch' (mode == 'scratch' or 'create_new_repo' — in both of the
--      latter two, the repository's structure was authored by Quan Harness
--      itself, or doesn't exist yet, so there is nothing an outside scan
--      could tell the person that they don't already know). See
--      app/routers/projects.py's create_project and
--      /docs/PHASE5_1_5_2_5_5_NOTES.md for the full reasoning, including the
--      one honest limitation this creates for every project row that
--      predates this migration (they all default to 'scratch' below, since
--      their real setup mode isn't recorded anywhere to backfill from).

create table deploy_runs (
    id uuid primary key default gen_random_uuid(),
    project_id uuid not null references projects(id) on delete cascade,
    status text not null default 'running' check (status in ('running', 'success', 'failed')),
    -- Which of `projects.deploy_targets`' entries this run is for — null for
    -- a project with a single implicit root (the common case: 'scratch'/
    -- 'create_new_repo' origin, or an 'imported' repo confirmed as one root).
    -- Set to that target's own `name` for one root of a confirmed monorepo.
    target_name text,
    phase text not null default 'detect' check (phase in ('detect', 'build', 'start', 'healthy')),
    -- 'dockerfile' is recorded even though §23.6's nested-sandboxing rule means
    -- this pipeline never actually attempts to build it — see
    -- deploy_pipeline.py's own docstring for why a Dockerfile is a detected-
    -- and-declined case, not a detected-and-failed one.
    stack text check (stack in ('nextjs', 'node', 'python', 'dockerfile', 'llm_fallback')),
    build_cmd text,
    run_cmd text,
    port integer,
    exit_code integer,
    stdout text not null default '',
    stderr text not null default '',
    -- §23.9 point 4's two treatments. Null until a diagnosis has actually run
    -- (or for a 'success' row, forever) — never defaulted to 'build', since an
    -- un-diagnosed failure must not silently look like a fixable code bug.
    failure_class text check (failure_class in ('build', 'environment')),
    diagnosis_text text,
    -- Never set when failure_class = 'environment' — §23.9 point 4: "Never use
    -- 'fix' framing" for an environment/runtime issue. Enforced in
    -- deploy_diagnosis.py, not by a DB constraint (a constraint can't see the
    -- LLM response that decides failure_class in the first place).
    suggested_fix_prompt text,
    created_at timestamptz not null default now(),
    completed_at timestamptz
);
alter table deploy_runs enable row level security;
create policy deploy_runs_owner_all on deploy_runs
    for all using (exists (select 1 from projects p where p.id = deploy_runs.project_id and p.user_id = auth.uid()))
    with check (exists (select 1 from projects p where p.id = deploy_runs.project_id and p.user_id = auth.uid()));

-- Powers "most recent deploy_run for this project" — both the Console tab's
-- default view and agent_loop.py's per-turn DEPLOY_DIAGNOSIS lookup (§23.9
-- point 3). Same shape as 0006's checkpoints_project_created_idx.
create index deploy_runs_project_created_idx on deploy_runs (project_id, created_at desc);


alter table projects add column repo_origin text not null default 'scratch'
    check (repo_origin in ('scratch', 'imported'));

-- Flips true once the person confirms a proposed deploy_targets shape from
-- §23.6's monorepo detection (or immediately, with no prompt, the moment a
-- 'scratch'-origin project's first deploy resolves its single implicit
-- root — see deploy_pipeline.py). From then on `projects.deploy_targets` is
-- used as-is on every deploy — "no repeated inference at deploy time."
alter table projects add column deploy_targets_confirmed boolean not null default false;
