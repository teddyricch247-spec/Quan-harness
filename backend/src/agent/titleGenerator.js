import { createResponse } from '../services/responsesApiClient.js';

const TITLE_INSTRUCTIONS = `You name conversations. You will be shown the first message of a new chat.
Reply with ONLY a short title for it — 3 to 6 words, title case, no surrounding quotes,
no trailing period, no markdown, nothing before or after it. Just the title text.`;

/**
 * One throwaway model call that names a session from its first message, the same way
 * most chat products auto-title a new conversation. Called exactly once, right after
 * a session's first turn finishes (see routes/sessions.js) — never on later turns.
 *
 * Deliberately isolated from the main/interview loops: it has no tools, replays no
 * history, and its failure mode is "the session just keeps its default title", not a
 * broken turn — see the try/catch around the call site.
 */
export async function generateSessionTitle({ provider, userText, effort }) {
  const { textOutput } = await createResponse({
    provider,
    instructions: TITLE_INSTRUCTIONS,
    input: [{ role: 'user', content: userText.slice(0, 4000) }],
    tools: [],
    effort,
    onEvent: () => {}, // never streamed to the UI — the frontend gets the final title only
  });

  return sanitizeTitle(textOutput);
}

function sanitizeTitle(raw) {
  if (!raw) return null;
  let title = raw.trim().split('\n')[0].trim();
  title = title.replace(/^[\s"'“”‘’]+|[\s"'“”‘’]+$/g, '').trim();
  title = title.replace(/[.。!！]+$/, '').trim();
  if (!title) return null;
  return title.length > 60 ? `${title.slice(0, 57).trim()}…` : title;
}
