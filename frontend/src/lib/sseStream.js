import { api } from './api.js';

/**
 * POSTs to `path` and calls onEvent(type, data) for every SSE frame the backend
 * writes, until the stream ends. Returns a controller with `.abort()` for the
 * "stop watching, keep it running server-side" case — the backend's own
 * disconnect-tolerance already covers what happens if the tab is just closed outright.
 */
export function streamTurn(sessionId, { text, reasoning_effort }, onEvent) {
  const controller = new AbortController();

  (async () => {
    let headers;
    try {
      headers = {
        'Content-Type': 'application/json',
        Authorization: await api.authHeader(),
      };
    } catch (err) {
      onEvent('error', { message: err.message });
      return;
    }

    let res;
    try {
      res = await fetch(`${api.backendUrl}/api/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ text, reasoning_effort }),
        signal: controller.signal,
      });
    } catch (err) {
      if (err.name !== 'AbortError') onEvent('error', { message: err.message });
      return;
    }

    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({}));
      onEvent('error', { message: body.error || `Request failed: ${res.status}` });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (err) {
        if (err.name !== 'AbortError') onEvent('error', { message: err.message });
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });

      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        parseFrame(frame, onEvent);
      }
    }
  })();

  return controller;
}

function parseFrame(frame, onEvent) {
  let eventType = 'message';
  const dataLines = [];
  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith('event:')) eventType = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  try {
    onEvent(eventType, JSON.parse(dataLines.join('\n')));
  } catch {
    // ignore malformed frames
  }
}
