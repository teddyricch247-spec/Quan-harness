// Which messages of a conversation Kael still reads.
//
// Every request re-sends the conversation, but only up to a budget: past
// HISTORY_MAX_CHARS of text (a picture counts as IMAGE_HISTORY_CHAR_COST
// characters), or HISTORY_MAX_MESSAGES messages, the oldest are left out. The
// backend does this silently (backend/app/chat_history.py, build_model_messages).
// This is the same arithmetic, so the page can draw a line in the conversation
// where Kael's memory of it now starts.
//
// The constants and the algorithm mirror the backend. If they disagree, the
// backend wins: fix this file. (A cross-language check lives in the session
// notes of the change that added this; the steps are the same as the backend's:
// drop what was never saved, keep the newest HISTORY_FETCH_LIMIT rows, merge
// neighbours of the same role, trim from the oldest end, never start on a reply.)

import type { ChatMessage } from '../types';

export const HISTORY_MAX_MESSAGES = 200;
export const HISTORY_MAX_CHARS = 400_000;
export const IMAGE_HISTORY_CHAR_COST = 4_000;
export const HISTORY_FETCH_LIMIT = 300;

// Length the way Python's len() counts it (characters, not UTF-16 units), because
// the backend's budget is counted that way.
const characters = (s: string): number => {
  if (!/[\ud800-\udbff]/.test(s)) return s.length; // no pairs: the common, fast case
  let n = s.length;
  for (let i = 0; i < s.length - 1; i++) {
    const hi = s.charCodeAt(i);
    if (hi >= 0xd800 && hi <= 0xdbff) {
      const lo = s.charCodeAt(i + 1);
      if (lo >= 0xdc00 && lo <= 0xdfff) {
        n--;
        i++;
      }
    }
  }
  return n;
};

interface Row {
  index: number;
  role: 'user' | 'assistant';
  text: string;
  images: number;
}

// The index (in `messages`) of the first message Kael still reads, or null when
// it reads the whole conversation. Everything before that index is out of its view.
export function firstMessageKaelReads(messages: ChatMessage[]): number | null {
  const rows: Row[] = [];
  messages.forEach((m, index) => {
    if (m.id === 'msg_welcome') return; // the greeting is never saved
    if (m.role !== 'user' && m.role !== 'assistant') return;
    if (m.role === 'assistant' && m.error) return; // a failed reply was never saved
    if (m.role === 'user') {
      const next = messages[index + 1];
      if (next && next.role === 'assistant' && next.error) return; // a send that failed was never saved
    }
    const images = m.role === 'user' ? (m.images?.length ?? m.imageCount ?? 0) : 0;
    if (!m.content.trim() && images === 0) return;
    rows.push({ index, role: m.role, text: m.content, images });
  });

  // The backend reads only the newest HISTORY_FETCH_LIMIT saved messages.
  const recent = rows.slice(-HISTORY_FETCH_LIMIT);

  // Neighbours of the same role are merged into one turn.
  const merged: Array<Row & { first: number }> = [];
  for (const row of recent) {
    const last = merged[merged.length - 1];
    if (last && last.role === row.role) {
      last.text = last.text.trim() && row.text.trim() ? `${last.text}\n\n${row.text}` : last.text || row.text;
      last.images += row.images;
    } else {
      merged.push({ ...row, first: row.index });
    }
  }

  const weight = (m: Row): number => characters(m.text) + IMAGE_HISTORY_CHAR_COST * m.images;
  let total = merged.reduce((n, m) => n + weight(m), 0);
  let start = 0;
  while (merged.length - start > 1 && (merged.length - start > HISTORY_MAX_MESSAGES || total > HISTORY_MAX_CHARS)) {
    total -= weight(merged[start]);
    start++;
  }
  // A conversation never opens on a reply.
  while (merged.length - start > 1 && merged[start].role === 'assistant') start++;

  const droppedSaved = rows.length - recent.length > 0;
  if (start === 0 && !droppedSaved) return null;
  return merged[start]?.first ?? null;
}
