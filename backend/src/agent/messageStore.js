import { supabaseAdmin } from '../supabaseAdmin.js';

// Assistant-authored item types that are real Responses API output — safe to replay
// verbatim back into input[] on a later turn. Anything else stored under role
// 'assistant' (turn_summary, interview_handoff) is UI-only bookkeeping this harness
// writes for itself; it was never something the model produced or should ever see
// again.
const REPLAYABLE_ASSISTANT_TYPES = new Set(['message', 'function_call', 'reasoning']);

export async function loadMessageRows(sessionId) {
  const { data, error } = await supabaseAdmin
    .from('messages')
    .select('id, role, content, created_at')
    .eq('session_id', sessionId)
    .order('created_at', { ascending: true });
  if (error) throw new Error(`Failed to load session history: ${error.message}`);
  return data || [];
}

export async function saveRow(sessionId, role, content) {
  const { error } = await supabaseAdmin.from('messages').insert({ session_id: sessionId, role, content });
  if (error) throw new Error(`Failed to persist message: ${error.message}`);
}

/**
 * Turns one stored row back into a Responses API input[] item, exactly as it was sent
 * or received originally — or returns null if the row is UI-only bookkeeping that must
 * never be resent to the model (turn_summary, interview_handoff, etc.).
 */
export function rowToInputItem(row) {
  if (row.role === 'user') return { role: 'user', content: row.content.text };
  if (row.role === 'tool') return row.content; // function_call_output — always replayable
  if (row.role === 'assistant' && REPLAYABLE_ASSISTANT_TYPES.has(row.content?.type)) return row.content;
  return null;
}

/** Convenience: load a session's full replayable history in one call. */
export function loadHistoryItems(rows) {
  return rows.map(rowToInputItem).filter(Boolean);
}
