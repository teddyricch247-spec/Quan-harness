# Word-by-word replies — how it works and what is not verified

## What you get
While the model is writing its answer, the text appears in the chat as it is written, like other AI apps. When the model
finishes, that live text is replaced by the normal saved message. Nothing about saving, history, or the turn loop changed.

## How it works (one paragraph)
`llm_client.call_llm` asks the provider for a *stream* (only for the agent's own turn call), collects the pieces into the
same single response as before, and hands each piece of text to `live_text.py`. That puts it on the same per-session queue
the real events use, `routers/agent.py` sends it to the browser as `delta` frames, and `ChatPane.tsx` shows it in a bubble
at the end of the chat. A `reset` frame drops the bubble when a failed attempt is retried. A viewer who connects or
reconnects mid-reply is first sent the text so far, then only the new pieces (each has a sequence number).

## Why `agent_loop.py` was not touched
I tried to edit `agent_loop.py` directly, but could not produce a byte-exact copy of that 106 KB file to send you (mine was
3 bytes off and I could not find where), so I would not ship a replacement of the core loop. The design needs no change there:
- **Which call streams:** only the agent's own turn call, recognised by its system prompt starting with the harness's static
  prompt (`llm_client._is_main_agent_call`; the same recognition prompt caching already uses).
- **Whose screen it streams to:** the session of the turn the call is running inside. Every way of starting a turn ends up as
  an `agent_loop._run(session_id, ...)` task, and `turn_control.session_of_current_turn` reads the session from it. That
  includes the first message of a new project (started from `routers/projects.py`) and scheduled runs. `routers/agent.py`
  also marks the turns it starts explicitly (`live_text.streaming_for`), which is now only a second route to the same answer.
If either recognition fails, the effect is only "no live text"; the turn itself is unaffected. Stop uses the same lookup.

## What is NOT verified (no real provider, no browser build here)
- **A real provider stream.** Tested with scripted fake chunks only. The pinned litellm (1.55.4) chunk shapes, usage in the
  last chunk (`stream_options`), and tool-call fragments differ a little between providers. `stream_options` and "can't
  stream" are handled by falling back, but nothing has run against OpenRouter, DeepSeek, Anthropic or OpenAI.
- **Token counts.** If a provider sends no usage while streaming, `input_tokens` is 0 and the loop falls back to its own
  estimate for compaction — it still works, just less precisely.
- **The frontend build.** `ChatPane.tsx` was syntax-checked, not built (`next build`) or tried on a phone.
- **A look and feel detail.** Text streams as a normal reply. If the model then calls tools, that same text is saved as
  quiet narration inside the collapsed activity line, so it may visibly shrink at that moment.
- Your existing test suite was not run. New tests: `backend/tests/test_llm_streaming.py`, `backend/tests/test_live_text.py`,
  and `frontend/scripts/test-sse.ts` (run with `npx tsx scripts/test-sse.ts` in `frontend/`).

## Stop button and thinking text
Done afterwards, the same way (no edit to `agent_loop.py`): see `docs/STOP_AND_THINKING_NOTES.md`.
