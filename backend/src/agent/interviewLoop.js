import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createResponse, extractFunctionCalls } from '../services/responsesApiClient.js';
import { executeTool } from './tools.js';
import { fillTemplate } from './promptTemplate.js';
import { safeParseArgs } from './util.js';
import { loadMessageRows, loadHistoryItems, saveRow } from './messageStore.js';
import { supabaseAdmin } from '../supabaseAdmin.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sharedDir = path.join(__dirname, '..', '..', '..', 'shared');

const interviewPrompt = readFileSync(path.join(sharedDir, 'interview-agent-system-prompt.md'), 'utf-8');
const interviewTools = JSON.parse(readFileSync(path.join(sharedDir, 'interview-agent-tools.json'), 'utf-8'));

const MAX_ROUNDS = 8; // read-only tool round-trips allowed before the agent must just ask its question

/**
 * Runs one turn of the prompt-maker agent — a separate agent from the main coding
 * agent in loop.js, with its own system prompt, its own (read-only) tool set, and its
 * own message history (this session's `messages` rows; never the builder's).
 *
 * Unlike the builder's loop, most turns here end in plain conversational text with no
 * tool call — that's the *normal* case (the agent asking a question and waiting for a
 * reply), not a stalled turn.
 *
 * When the model calls finalize_prompt, this creates a brand-new `build` session
 * containing nothing but the generated prompt — the builder never sees this session's
 * history. The new session id + prompt are handed back to the frontend via the
 * `handoff` SSE event; actually running the builder's first turn happens through the
 * normal POST /api/sessions/:id/messages path, triggered client-side once it
 * navigates there (see SessionView.jsx's `autoSendPrompt` handling). That keeps a
 * strict "one session, one active loop" invariant instead of nesting two agent loops
 * inside one HTTP response.
 */
export async function runInterviewTurn({ project, session, userText, provider, effort, sse }) {
  const priorRows = await loadMessageRows(session.id);
  let input = [...loadHistoryItems(priorRows), { role: 'user', content: userText }];

  await saveRow(session.id, 'user', { text: userText });

  const instructions = buildInstructions(project);
  const ctx = { project, updateProject: async () => {} }; // read-only agent; never mutates the project row

  let handoff = null;

  for (let round = 0; round < MAX_ROUNDS; round += 1) {
    const { outputItems } = await createResponse({
      provider,
      instructions,
      input,
      tools: interviewTools,
      effort,
      onEvent: (type, payload) => sse.send(type, payload),
    });

    if (outputItems.length === 0) break;

    input = [...input, ...outputItems];
    for (const item of outputItems) {
      await saveRow(session.id, 'assistant', item);
    }

    const calls = extractFunctionCalls(outputItems);
    if (calls.length === 0) break; // plain text — the agent asked something; wait for the user's reply

    for (const call of calls) {
      const args = safeParseArgs(call.arguments);
      sse.send('tool_call', { name: call.name, arguments: args });

      if (call.name === 'finalize_prompt') {
        const output = { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify({ received: true }) };
        input.push(output);
        await saveRow(session.id, 'tool', output);
        handoff = await spawnBuildSession({ project, interviewSession: session, title: args.title, prompt: args.prompt });
        break; // nothing after finalize_prompt is processed, same rule as finish_task
      }

      let result;
      try {
        result = await executeTool(call.name, args, ctx);
      } catch (err) {
        result = { error: err.message };
      }
      const output = { type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) };
      input.push(output);
      await saveRow(session.id, 'tool', output);
    }

    if (handoff) break;
  }

  if (handoff) {
    await saveRow(session.id, 'assistant', {
      type: 'interview_handoff',
      title: handoff.title,
      session_id: handoff.sessionId,
    });
    // completed_at locks this interview session against further messages (enforced in
    // routes/sessions.js) — it did its job, and replaying its history into future
    // calls was never valid Responses-API input anyway (see messageStore.js).
    await supabaseAdmin
      .from('sessions')
      .update({ updated_at: new Date().toISOString(), completed_at: new Date().toISOString() })
      .eq('id', session.id);
    sse.send('handoff', { session_id: handoff.sessionId, title: handoff.title, prompt: handoff.prompt });
  } else {
    await supabaseAdmin.from('sessions').update({ updated_at: new Date().toISOString() }).eq('id', session.id);
    sse.send('done', {});
  }
}

function buildInstructions(project) {
  return fillTemplate(interviewPrompt, {
    PROJECT_NAME: project.name,
    GITHUB_REPO: project.github_repo,
    GITHUB_DEFAULT_BRANCH: project.github_default_branch,
    STACK: project.stack,
    PROJECT_MEMORY: project.memory,
  });
}

async function spawnBuildSession({ project, interviewSession, title, prompt }) {
  const insert = {
    project_id: project.id,
    title: (title || '').trim() || 'New session',
    kind: 'build',
    origin_session_id: interviewSession.id,
    provider: interviewSession.provider,
    reasoning_effort: interviewSession.reasoning_effort,
  };
  const { data, error } = await supabaseAdmin.from('sessions').insert(insert).select().single();
  if (error) throw new Error(`Failed to create the build session: ${error.message}`);
  return { sessionId: data.id, title: data.title, prompt };
}
