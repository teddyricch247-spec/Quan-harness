import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createResponse } from '../services/responsesApiClient.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sharedDir = path.join(__dirname, '..', '..', '..', 'shared');

const criticPrompt = readFileSync(path.join(sharedDir, 'critic-system-prompt.md'), 'utf-8');

/**
 * Runs the critic. Deliberately the simplest of the three model roles in this
 * harness: no tools, no structured output, no multi-round loop — one message in, one
 * plain-text reply out. It never sees anything the caller doesn't hand it directly,
 * and it never mutates anything; agent/loop.js is what decides whether to call it at
 * all, and it's the one enforcing the two-call-per-turn cap, not this module.
 *
 * This is distinct from runVerifier (agent/verifier.js), which reads files, runs in
 * a tool loop, and returns structured corrections that get auto-applied. The critic
 * is a second opinion on whether the work is any good, not a check for breakage —
 * its output is meant to be read and judged by the main agent, never applied as-is.
 *
 * `provider` is the same resolved registry entry (see config.js) the rest of the
 * turn is using — passed through explicitly rather than read from global config, so
 * the critic always runs on whichever provider the session is actually set to.
 */
export async function runCritique({ project, taskText, diffsSoFar, focus, provider, effort }) {
  const diffsBlock = diffsSoFar
    .map((d) => `### ${d.path} (${d.op})\n\n\`\`\`\n${d.content ?? '(deleted)'}\n\`\`\``)
    .join('\n\n');

  const input = [
    {
      role: 'user',
      content: [
        `Project: ${project.name} (stack: ${project.stack || 'not yet set'})`,
        project.memory ? `Project memory:\n${project.memory}` : null,
        '',
        `What the user asked for this turn: ${taskText}`,
        '',
        `What's been written so far this turn:\n\n${diffsBlock}`,
        focus ? `\nThe main agent specifically wants your take on: ${focus}` : null,
      ]
        .filter((line) => line !== null)
        .join('\n'),
    },
  ];

  const { textOutput } = await createResponse({
    provider,
    instructions: criticPrompt,
    input,
    tools: [],
    effort,
    onEvent: () => {}, // the critic's own reasoning/text isn't streamed to the UI live
  });

  return { critique: (textOutput || '').trim() || 'No critique text came back — treat that as a pass.' };
}
