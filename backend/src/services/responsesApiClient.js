/**
 * Thin client for any OpenAI-Responses-API-compatible endpoint (client.responses.create
 * equivalent, done over raw fetch so we don't depend on an SDK's exact method surface).
 * It was originally written against DeepSeek's Responses API specifically; it now takes
 * a `provider` object (see config.js's `providers` registry) so it works unmodified
 * against DeepSeek, OpenAI's real Responses API, Azure OpenAI's Responses API, or any
 * other endpoint that speaks the same shape — which one it's pointed at is entirely a
 * property of the `provider` passed in, nothing hardcoded here.
 *
 * The Responses API is stateless: callers must resend the full `instructions` +
 * `input[]` on every call, including follow-up calls after a tool result — this module
 * doesn't do anything to hide that, on purpose, since the agent loops need to control
 * exactly what's in input[] on each round.
 *
 * Note: DeepSeek's docs warn against replaying `reasoning_content` back into history
 * on their older Chat Completions API — but that warning doesn't apply here. The
 * Responses API explicitly lists `reasoning` as a supported input item type and
 * expects the raw `reasoning` output item to be replayed verbatim alongside
 * `message`/`function_call`/`function_call_output` items, which is exactly what
 * agent/messageStore.js does. Don't "fix" that by stripping reasoning items back out.
 *
 * onEvent(type, payload) is called live as text streams in:
 *   - onEvent('reasoning_delta', { delta })
 *   - onEvent('content_delta', { delta })
 *
 * The returned promise resolves once the response is complete, with:
 *   { outputItems, textOutput }
 * where outputItems is the full array of items the provider produced this call (in
 * order: reasoning, then message and/or function_call items) and textOutput is the
 * concatenated assistant text.
 */
export async function createResponse({ provider, instructions, input, tools, effort, onEvent, jsonSchema }) {
  const supportsReasoning = Array.isArray(provider.reasoningEfforts) && provider.reasoningEfforts.length > 0;
  if (supportsReasoning && !provider.reasoningEfforts.includes(effort)) {
    throw new Error(
      `Unknown reasoning effort '${effort}' for provider '${provider.id}'. Expected one of: ${provider.reasoningEfforts.join(', ')}.`,
    );
  }

  const res = await fetch(`${provider.baseUrl}/responses`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${provider.apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: provider.model,
      instructions,
      input,
      tools,
      stream: true,
      // Only sent for providers that actually declared reasoning-effort levels — a
      // provider with an empty list gets no `reasoning` field at all, rather than the
      // harness guessing a value it might reject.
      ...(supportsReasoning ? { reasoning: { effort } } : {}),
      // Only sent when the caller wants constrained JSON output (the verifier).
      // Follows the OpenAI Responses API's structured-output shape; re-check the
      // provider's own docs if this stops being honored.
      ...(jsonSchema ? { text: { format: { type: 'json_schema', ...jsonSchema } } } : {}),
    }),
  });

  if (!res.ok || !res.body) {
    const body = await res.text().catch(() => '');
    throw new Error(`${provider.label || provider.id} responses.create → ${res.status}: ${body.slice(0, 1000)}`);
  }

  return consumeSSE(res.body, onEvent);
}

async function consumeSSE(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');

  let buffer = '';
  let finalResponse = null;               // set if a response.completed event arrives
  const itemsById = new Map();            // fallback accumulator, keyed by item id
  const itemOrder = [];
  let textOutput = '';

  const handleEvent = (eventType, data) => {
    switch (eventType) {
      case 'response.reasoning_text.delta':
        if (data.delta) onEvent('reasoning_delta', { delta: data.delta });
        break;
      case 'response.output_text.delta':
        if (data.delta) {
          textOutput += data.delta;
          onEvent('content_delta', { delta: data.delta });
        }
        break;
      case 'response.output_item.done':
        if (data.item?.id && !itemsById.has(data.item.id)) itemOrder.push(data.item.id);
        if (data.item?.id) itemsById.set(data.item.id, data.item);
        break;
      case 'response.completed':
      case 'response.incomplete':
        finalResponse = data.response || null;
        break;
      case 'response.failed': {
        const detail = data.response?.error?.message || JSON.stringify(data.response?.error) || 'unknown error';
        throw new Error(`Provider response failed: ${detail}`);
      }
      case 'error':
        throw new Error(`Provider stream error: ${data.message || JSON.stringify(data)}`);
      default:
        break; // response.created, response.in_progress, content_part events, etc. — ignored
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    // SSE frames are separated by a blank line.
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      parseFrame(frame, handleEvent);
    }
  }
  // Flush any trailing frame without a final blank line.
  if (buffer.trim()) parseFrame(buffer, handleEvent);

  const outputItems = finalResponse?.output ?? itemOrder.map((id) => itemsById.get(id));
  const resolvedText = finalResponse
    ? outputItems
        .filter((item) => item.type === 'message')
        .flatMap((item) => (item.content || []).filter((c) => c.type === 'output_text').map((c) => c.text))
        .join('')
    : textOutput;

  return { outputItems: outputItems || [], textOutput: resolvedText };
}

function parseFrame(frame, handleEvent) {
  let eventType = 'message';
  const dataLines = [];

  for (const rawLine of frame.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (line.startsWith('event:')) eventType = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }

  if (dataLines.length === 0) return;
  const raw = dataLines.join('\n');
  if (raw === '[DONE]') return;

  let data;
  try {
    data = JSON.parse(raw);
  } catch {
    return; // Skip malformed frames rather than crashing the whole turn.
  }

  // Some providers put the event name inside the JSON payload (data.type) instead of
  // an `event:` line — prefer that when present.
  handleEvent(data.type || eventType, data);
}

/** Extract just the function_call items from a resolved output, in call order. */
export function extractFunctionCalls(outputItems) {
  return outputItems.filter((item) => item.type === 'function_call');
}
