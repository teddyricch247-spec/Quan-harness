import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createResponse, extractFunctionCalls } from '../services/deepseek.js';
import { executeTool, makeProjectUpdater } from './tools.js';
import { runVerifier } from './verifier.js';
import { runCritique } from './critic.js';
import { fillTemplate } from './promptTemplate.js';
import { safeParseArgs } from './util.js';
import { supabaseAdmin } from '../supabaseAdmin.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sharedDir = path.join(__dirname, '..', '..', '..', 'shared');

const mainPrompt = readFileSync(path.join(sharedDir, 'main-agent-system-prompt.md'), 'utf-8');
const mainTools = JSON.parse(readFileSync(path.join(sharedDir, 'main-agent-tools.json'), 'utf-8'));

const MAX_ROUNDS = 25; // safety cap on tool-call round-trips within a single turn
const MAX_CRITIQUE_CALLS = 2; // the critic always finds *something* — bound how many times the agent can ask

/**
 * Runs one full turn: load history → call the model → execute whatever tools it
 * calls (optionally pausing for its own self-critique, up to MAX_CRITIQUE_CALLS
 * times) → repeat until finish_task → verifier → deployment status → persist → done.
 * `sse.send(event, data)` writes one SSE frame; failures are swallowed so a dropped
 * client connection never aborts the loop — see the disconnect-tolerance note below.
 */
export async function runTurn({ project, session, userText, effort, sse }) {
  const priorRows = await loadMessageRows(session.id);
  const history = priorRows.map(rowToInputItem);

  await saveRow(session.id, 'user', { text: userText });

  let input = [...history, { role: 'user', content: userText }];
  const instructions = buildInstructions(project);
  const ctx = { project, updateProject: makeProjectUpdater(project) };

  const diffsThisTurn = [];
  const critiquesThisTurn = [];
  let critiqueCallsUsed = 0;
  let finishArgs = null;

  for (let round = 0; round < MAX_ROUNDS && !finishArgs; round += 1) {
    const { outputItems } = await createResponse({
      instructions,
      input,
      tools: mainTools,
      effort,
      onEvent: (type, payload) => sse.send(type, payload),
    });

    if (outputItems.length === 0) break; // nothing more to do — avoid spinning forever

    input = [...input, ...outputItems];
    for (const item of outputItems) {
      await saveRow(session.id, 'assistant', item);
    }

    const calls = extractFunctionCalls(outputItems);
    if (calls.length === 0) break; // model produced only text with no tool call — treat the turn as stalled, not looped

    for (const call of calls) {
      const args = safeParseArgs(call.arguments);
      sse.send('tool_call', { name: call.name, arguments: args });

      if (call.name === 'finish_task') {
        finishArgs = args;
        const output = { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify({ received: true }) };
        input.push(output);
        await saveRow(session.id, 'tool', output);
        break; // nothing after finish_task is processed, even within the same batch of calls
      }

      // Handled directly rather than via executeTool: it needs to call a second
      // model and enforce a cross-call budget, neither of which fits the plain
      // (args, ctx) → result shape the mechanical tools in tools.js use.
      if (call.name === 'request_critique') {
        critiqueCallsUsed += 1;
        let critiqueResult;
        if (critiqueCallsUsed > MAX_CRITIQUE_CALLS) {
          critiqueResult = {
            critique: `Critique budget for this turn is used up (max ${MAX_CRITIQUE_CALLS} calls). Proceed on your own judgment and move to finish_task.`,
          };
        } else if (diffsThisTurn.length === 0) {
          critiqueResult = {
            critique: "Nothing has been written yet this turn — there's nothing to critique yet. Implement something first, then ask again if you want a second opinion.",
          };
        } else {
          try {
            critiqueResult = await runCritique({
              project,
              taskText: userText,
              diffsSoFar: diffsThisTurn,
              focus: args.focus,
              effort,
            });
            critiquesThisTurn.push({ round: critiqueCallsUsed, focus: args.focus || null, critique: critiqueResult.critique });
          } catch (err) {
            critiqueResult = { critique: `Critique unavailable this round: ${err.message}` };
          }
        }
        const output = { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(critiqueResult) };
        input.push(output);
        await saveRow(session.id, 'tool', output);
        continue; // more rounds still expected — unlike finish_task, this never ends the turn
      }

      let result;
      try {
        result = await executeTool(call.name, args, ctx);
      } catch (err) {
        result = { error: err.message };
      }

      if (call.name === 'github_write_file' && !result.error) {
        diffsThisTurn.push({ path: args.path, content: args.content, op: 'write' });
      } else if (call.name === 'github_delete_file' && !result.error) {
        diffsThisTurn.push({ path: args.path, content: null, op: 'delete' });
      }

      const output = { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) };
      input.push(output);
      await saveRow(session.id, 'tool', output);
    }
  }

  if (!finishArgs) {
    finishArgs = { summary: "Stopped without calling finish_task — check the tool actions above for what happened." };
  }

  let verifierNotes = null;
  if (diffsThisTurn.length > 0) {
    const verifierResult = await runVerifier({ project, summary: finishArgs.summary, diffs: diffsThisTurn, effort });
    verifierNotes = verifierResult.notes || null;
    if (verifierResult.issues_found && verifierResult.corrections?.length) {
      for (const correction of verifierResult.corrections) {
        try {
          await executeTool(
            'github_write_file',
            { path: correction.path, content: correction.content, commit_message: 'fix: verifier corrections' },
            ctx,
          );
          sse.send('tool_call', { name: 'github_write_file', arguments: { path: correction.path, commit_message: 'fix: verifier corrections' } });
        } catch (err) {
          verifierNotes = `${verifierNotes ?? ''} (Failed to apply a correction to ${correction.path}: ${err.message})`.trim();
        }
      }
    }
  }

  let deploymentStatus = null;
  if (project.vercel_project_id) {
    try {
      deploymentStatus = await executeTool('vercel_deployment_status', {}, ctx);
    } catch (err) {
      deploymentStatus = { state: 'error', message: err.message };
    }
  }

  await saveRow(session.id, 'assistant', {
    type: 'turn_summary',
    summary: finishArgs.summary,
    verifier_notes: verifierNotes,
    critique_notes: critiquesThisTurn.length ? critiquesThisTurn : null,
    deployment_status: deploymentStatus,
  });

  if (finishArgs.memory_update) await ctx.updateProject({ memory: finishArgs.memory_update });
  if (finishArgs.stack) await ctx.updateProject({ stack: finishArgs.stack });

  await supabaseAdmin.from('sessions').update({ updated_at: new Date().toISOString() }).eq('id', session.id);

  sse.send('done', {
    summary: finishArgs.summary,
    verifier_notes: verifierNotes,
    critique_notes: critiquesThisTurn,
    deployment_status: deploymentStatus,
  });
}

function buildInstructions(project) {
  return fillTemplate(mainPrompt, {
    PROJECT_NAME: project.name,
    GITHUB_REPO: project.github_repo,
    GITHUB_DEFAULT_BRANCH: project.github_default_branch,
    STACK: project.stack,
    VERCEL_PROJECT_ID: project.vercel_project_id,
    PROJECT_MEMORY: project.memory,
  });
}

async function loadMessageRows(sessionId) {
  const { data, error } = await supabaseAdmin
    .from('messages')
    .select('role, content, created_at')
    .eq('session_id', sessionId)
    .order('created_at', { ascending: true });
  if (error) throw new Error(`Failed to load session history: ${error.message}`);
  return data || [];
}

async function saveRow(sessionId, role, content) {
  const { error } = await supabaseAdmin.from('messages').insert({ session_id: sessionId, role, content });
  if (error) throw new Error(`Failed to persist message: ${error.message}`);
}

/** Turns a stored row back into a Responses API input[] item, exactly as it was sent originally. */
function rowToInputItem(row) {
  if (row.role === 'user') return { role: 'user', content: row.content.text };
  return row.content; // assistant → raw message/function_call item; tool → function_call_output item
}
