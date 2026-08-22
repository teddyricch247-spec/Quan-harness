import * as github from '../services/github.js';
import * as vercel from '../services/vercel.js';
import * as tavily from '../services/tavily.js';
import { supabaseAdmin } from '../supabaseAdmin.js';

/**
 * Each handler takes (args, ctx) where ctx = { project, updateProject }.
 * `ctx.project` is the live project row for this turn — handlers that create a repo
 * or Vercel project mutate it in place (and persist to Postgres immediately) so that
 * every subsequent tool call in the SAME turn sees the update without waiting for
 * finish_task. This is the "mechanical fact, not a model judgment call" persistence
 * described in the build spec.
 */
export const toolHandlers = {
  async github_list_tree({ branch }, ctx) {
    requireRepo(ctx);
    const resolvedBranch = branch || ctx.project.github_default_branch;
    const paths = await github.listTree(ctx.project.github_repo, resolvedBranch);
    return { branch: resolvedBranch, paths };
  },

  async github_read_file({ path }, ctx) {
    requireRepo(ctx);
    const { content } = await github.readFile(ctx.project.github_repo, path, ctx.project.github_default_branch);
    return { path, content };
  },

  async github_write_file({ path, content, commit_message }, ctx) {
    requireRepo(ctx);
    const result = await github.writeFile(
      ctx.project.github_repo,
      path,
      content,
      commit_message,
      ctx.project.github_default_branch,
    );
    return { path, committed: true, commit_sha: result.commitSha };
  },

  async github_delete_file({ path, commit_message }, ctx) {
    requireRepo(ctx);
    const result = await github.deleteFile(
      ctx.project.github_repo,
      path,
      commit_message,
      ctx.project.github_default_branch,
    );
    return { path, deleted: true, commit_sha: result.commitSha };
  },

  async github_create_repo({ name, private: isPrivate }, ctx) {
    if (ctx.project.github_repo) {
      throw new Error(`Project already has a repository (${ctx.project.github_repo}) — refusing to create another.`);
    }
    const { fullName, defaultBranch } = await github.createRepo(name, isPrivate !== false);
    await ctx.updateProject({ github_repo: fullName, github_default_branch: defaultBranch });
    return { github_repo: fullName, github_default_branch: defaultBranch };
  },

  async vercel_create_project({ name }, ctx) {
    requireRepo(ctx);
    if (ctx.project.vercel_project_id) {
      throw new Error('Project is already linked to a Vercel project — refusing to create another.');
    }
    const { projectId } = await vercel.createProject(name, ctx.project.github_repo);
    await ctx.updateProject({ vercel_project_id: projectId });
    return { vercel_project_id: projectId };
  },

  async tavily_search({ query }, _ctx) {
    const results = await tavily.search(query);
    return { query, results };
  },

  async vercel_deployment_status(_args, ctx) {
    if (!ctx.project.vercel_project_id) {
      return { state: 'unlinked', message: 'This project has no linked Vercel project yet.' };
    }
    return vercel.deploymentStatus(ctx.project.vercel_project_id);
  },

  // finish_task performs no external action itself — the agent loop reads its
  // arguments (summary / memory_update / stack) directly and ends the turn. It still
  // needs a handler so the dispatch loop can treat every tool call uniformly and log
  // a function_call_output for it in the message history.
  async finish_task(args, _ctx) {
    return { received: true, summary: args.summary };
  },

  // Same story as finish_task: agent/loop.js special-cases request_critique before
  // ever reaching executeTool, because it needs to call a second model and enforce a
  // cross-call budget — neither fits the plain (args, ctx) → result shape every other
  // handler here uses. This entry exists only so the dispatch table stays complete
  // and defensive against a future refactor that routes it through executeTool.
  async request_critique(_args, _ctx) {
    throw new Error('request_critique is handled directly in agent/loop.js and should never reach executeTool.');
  },
};

function requireRepo(ctx) {
  if (!ctx.project.github_repo) {
    throw new Error(
      "This project has no repository yet. Call github_create_repo (then vercel_create_project) before any file operation.",
    );
  }
}

/** Builds ctx.updateProject bound to one project row, applying to both Postgres and the in-memory object. */
export function makeProjectUpdater(project) {
  return async (patch) => {
    Object.assign(project, patch);
    const { error } = await supabaseAdmin.from('projects').update(patch).eq('id', project.id);
    if (error) throw new Error(`Failed to persist project update: ${error.message}`);
  };
}

export async function executeTool(name, args, ctx) {
  const handler = toolHandlers[name];
  if (!handler) throw new Error(`Unknown tool: ${name}`);
  return handler(args, ctx);
}
