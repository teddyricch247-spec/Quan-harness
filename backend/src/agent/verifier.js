import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createResponse, extractFunctionCalls } from '../services/deepseek.js';
import { executeTool } from './tools.js';
import { safeParseArgs } from './util.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sharedDir = path.join(__dirname, '..', '..', '..', 'shared');

const verifierPrompt = readFileSync(path.join(sharedDir, 'verifier-system-prompt.md'), 'utf-8');
const verifierTools = JSON.parse(readFileSync(path.join(sharedDir, 'verifier-tools.json'), 'utf-8'));
const outputSchema = JSON.parse(readFileSync(path.join(sharedDir, 'verifier-output-schema.json'), 'utf-8'));

const MAX_VERIFIER_TOOL_ROUNDS = 6;

/**
 * Runs the verifier once per finish_task. No shared conversation history — just this
 * turn's summary + diffs. The only tool it has is github_read_file, bound to the same
 * repo the main agent was just working in (ctx.project comes from the caller so the
 * model itself never chooses a repo).
 */
export async function runVerifier({ project, summary, diffs, effort }) {
  const diffsBlock = diffs
    .map((d) => `### ${d.path} (${d.op})\n\n\`\`\`\n${d.content ?? '(deleted)'}\n\`\`\``)
    .join('\n\n');

  let input = [
    {
      role: 'user',
      content: [
        `Main agent's summary of this turn: ${summary}`,
        '',
        diffs.length ? `Diffs written this turn:\n\n${diffsBlock}` : 'No files were written or deleted this turn.',
      ].join('\n'),
    },
  ];

  const ctx = { project, updateProject: async () => {} }; // verifier never mutates the project row

  const finalText = await runToolLoop(input, verifierTools, effort, ctx);
  const parsed = tryParse(finalText);
  if (parsed) return parsed;

  // One retry, per the build spec, on a malformed response — a fresh round-trip with
  // an explicit reminder appended, not just a re-parse of the same text.
  const retryInput = [
    ...input,
    { role: 'assistant', content: finalText ?? '' },
    {
      role: 'user',
      content:
        'That response was not valid JSON matching the required schema. Reply with ONLY the JSON object — no prose, no code fence.',
    },
  ];
  const retryText = await runToolLoop(retryInput, verifierTools, effort, ctx);
  const retryParsed = tryParse(retryText);
  if (retryParsed) return retryParsed;

  return { issues_found: false, notes: 'Verifier output was malformed after one retry; skipped.', corrections: [] };
}

async function runToolLoop(initialInput, tools, effort, ctx) {
  let input = initialInput;
  for (let round = 0; round < MAX_VERIFIER_TOOL_ROUNDS; round += 1) {
    const { outputItems, textOutput } = await createResponse({
      instructions: verifierPrompt,
      input,
      tools,
      effort,
      onEvent: () => {}, // the verifier's own reasoning/text isn't streamed to the UI
      jsonSchema: outputSchema,
    });

    const calls = extractFunctionCalls(outputItems);
    if (calls.length === 0) return textOutput;

    input = [...input, ...outputItems];
    for (const call of calls) {
      const args = safeParseArgs(call.arguments);
      let result;
      try {
        result = await executeTool(call.name, args, ctx);
      } catch (err) {
        result = { error: err.message };
      }
      input.push({
        type: 'function_call_output',
        call_id: call.call_id,
        output: JSON.stringify(result),
      });
    }
  }
  return null; // ran out of tool-call rounds without a final answer
}

function tryParse(text) {
  if (!text) return null;
  try {
    const parsed = JSON.parse(stripCodeFence(text));
    if (typeof parsed.issues_found !== 'boolean' || !Array.isArray(parsed.corrections)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function stripCodeFence(text) {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  return fenced ? fenced[1] : text;
}
