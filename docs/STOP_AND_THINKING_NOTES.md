# Stop button and thinking text

Like streaming (`docs/STREAMING_NOTES.md`), both are built **without editing `agent_loop.py`**.

## Do this first: one SQL migration (for saved thinking)
Run `db/migrations/0018_session_thinking_events.sql` in the Supabase SQL editor. It lets `session_events` hold a new event
type, `thinking`. Without it everything still works: thinking is shown live, but is not kept afterwards (the backend logs
"could not save the model's thinking" once and carries on). The migration rebuilds the existing constraint from its current
definition with `thinking` added; if the definition has an unexpected shape it raises and changes nothing. Running it twice
is harmless. It has not been run against a real database.

## Stop button
- While a turn is running, a **Stop** button appears above the message box. It calls `POST /sessions/{id}/stop`.
- `services/turn_control.py` finds the running turn's task (the `agent_loop._run` coroutine for that session) and cancels it,
  waits for it to end, adds a notice ("The person stopped this turn…"), sets the session to `completed` (the sessions table
  has no "stopped" status) and tells every open viewer.
- The notice is also read by the model on its next turn, as a `[System]` message, so it knows the last turn was cut off.
- What it does **not** undo: a command already started inside the workspace may keep running there until it ends; the loop
  just stops waiting for it. A step cut off mid-way is handled by the loop's existing recovery on the next turn (read-only
  calls re-run, others are marked "interrupted").
- Stop answers "nothing running" (HTTP 409, shown as nothing) if the turn ended just before the click. A turn waiting for an
  approval is not running, so Stop does not apply to it.
- It depends on `agent_loop._run(session_id, user_id)` keeping that name and first argument — and so does live streaming
  (it uses the same lookup to know which session a model call belongs to). `tests/test_turn_control.py` checks the real
  file for both, so a rename fails a test instead of silently breaking Stop and live text.

## Thinking text
- While the model thinks, the text appears live in a small muted "Thinking…" block; when the model call ends it is saved as
  one `thinking` event and shown as a collapsed **Thinking** row. Thinking that leads into a tool call folds into the
  collapsed activity line with it; thinking behind the final reply stays visible, collapsed, just above the reply.
- The saved thinking is **never sent back to the model** (`message_builder` skips event types it doesn't render).
- A credential's "show thinking" switch (`llm_credentials.reasoning.show = false`) hides it both live and saved.

### Thinking only appears if the provider sends it — not verified
- The pinned `litellm==1.55.4` may not pass an OpenRouter model's `reasoning` field through in a stream. If you turn thinking
  on for a model and see no "Thinking" at all, that is the likely cause; bumping litellm is the fix.
- DeepSeek credentials have thinking forced off by `llm_client.py` (a DeepSeek API limitation described there), so they
  never show any.
- Whitespace-only pieces of thinking are dropped by the existing text extractor, so a streamed paragraph break can be lost.

## Not verified
- Nothing here has run against a real model, a real database or a built frontend. New tests: `backend/tests/test_live_text.py`,
  `test_llm_streaming.py`, `test_turn_control.py`, and `frontend/scripts/test-sse.ts`, `test-thinking-rows.ts`
  (`npx tsx scripts/<name>.ts` in `frontend/`). Your existing tests were not run.
- `ChatPane.tsx` and `transcript.ts` were syntax-checked, not built.
