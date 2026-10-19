"""
Word-by-word streaming of the agent's reply — and of its thinking — before either exists as a saved event.

The durable event log stays the source of truth and is untouched: a reply is still written to session_events once, whole,
when the model call finishes. This module only carries the ephemeral "text so far" to anyone watching, so a viewer sees the
reply appear as it is written instead of all at once at the end. Nothing live is stored; after a restart it is simply gone,
and the finished `message` event is what every later viewer reads.

Two channels, same mechanism: the reply's text (`delta` frames) and the model's thinking (`thinking` frames). When a call
finishes, the thinking is also SAVED as one `thinking` event (see `save_thinking`) so it can be read afterwards; the reply
is saved by the agent loop as before.

How a delta travels
  llm_client.call_llm (the main agent call only) -> LiveSink.delta -> LiveTextRegistry -> agent_loop._broadcast
  -> the SSE queue of every watcher of that session -> routers/agent.py -> `event: delta` frames -> the browser.
It goes through the SAME per-session queue as the real events, so a delta and the `message` event that supersedes it can
never arrive out of order (two queues could not promise that, and a late delta after the finished message would show as a
stray half reply).

Which call streams: only the MAIN AGENT call of a turn (`llm_client._is_main_agent_call`: its system message starts with the
harness's static prompt). Which session it belongs to comes from the turn the call is running inside
(`turn_control.session_of_current_turn`), or from an explicit `streaming_for` binding (routers/agent.py still binds around
start_turn / send_interrupt / resume_after_approval; asyncio copies the context into the turn's task). A compaction summary,
a memory-extraction call or a delegated sub-task is never recognised as the main call, so none of them puts text on anyone's
screen. If recognition fails, the effect is only "no live text" — the turn itself is unaffected.

Reconnecting mid-reply: the registry keeps the text so far per channel (`snapshot`), the stream endpoint sends it first, and
every delta carries a `seq` so deltas already inside the snapshot are not applied twice.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Awaitable, Callable, Iterator

logger = logging.getLogger(__name__)

TEXT = "text"
THINKING = "thinking"

# Payload markers on agent_loop's broadcast queues. `id: 0` on a delta is deliberate: any consumer that skips payloads whose
# id it has already seen (routers/agent.py's old logic did) would skip it rather than crash on a missing key.
DELTA = "__text_delta__"
THINKING_DELTA = "__thinking_delta__"
RESET = "__text_reset__"

# A saved thinking event is capped so one runaway reasoning stream can't write an unbounded row.
MAX_THINKING_CHARS = 20_000

_bound_session: contextvars.ContextVar[str | None] = contextvars.ContextVar("live_text_session", default=None)


@contextlib.contextmanager
def streaming_for(session_id: str) -> Iterator[None]:
    """Mark the turn started inside this block as one whose reply should be streamed to the session's watchers. Wrap the call
    that STARTS the turn (the spawned task copies the context at that moment); it is reset on exit."""
    token = _bound_session.set(session_id)
    try:
        yield
    finally:
        _bound_session.reset(token)


def bound_session() -> str | None:
    """The session whose watchers should see this call's text: an explicit `streaming_for` binding if there is one, else the
    session of the agent-loop turn the caller is running inside (turn_control.session_of_current_turn). The second is what
    makes every way of starting a turn stream — including the first message of a new project, which starts its turn from
    routers/projects.py, not from the router that binds."""
    bound = _bound_session.get()
    if bound is not None:
        return bound
    from app.services import turn_control

    return turn_control.session_of_current_turn()


async def _append_via_repository(session_id: str, role: str, event_type: str, content: dict) -> dict:
    from app.repositories import session_events as session_events_repo

    return await session_events_repo.append(session_id, role, event_type, content)


class LiveTextRegistry:
    """The text-so-far per session and channel, and its fan-out. `broadcast(session_id, payload)` and `append_event` are
    injected so this is testable alone."""

    def __init__(self, broadcast: Callable[[str, dict], None], append_event: Callable[..., Awaitable[dict]] | None = None):
        self._broadcast = broadcast
        self._append_event = append_event or _append_via_repository
        self._live: dict[str, dict[str, dict]] = {}
        self._warned_save = False

    def delta(self, session_id: str, text: str, channel: str = TEXT) -> None:
        if not text:
            return
        live = self._live.setdefault(session_id, {}).setdefault(channel, {"text": "", "seq": 0})
        live["text"] += text
        live["seq"] += 1
        kind = DELTA if channel == TEXT else THINKING_DELTA
        self._send(session_id, {"event_type": kind, "id": 0, "text": text, "seq": live["seq"]})

    def reset(self, session_id: str) -> None:
        """Discard everything shown (the reply is being retried, or the call failed). A no-op when nothing is live."""
        if self._live.pop(session_id, None):
            self._send(session_id, {"event_type": RESET, "id": 0})

    def end(self, session_id: str) -> None:
        """The call finished. Silent: the finished events that follow are what replace the live text on screen."""
        self._live.pop(session_id, None)

    def snapshot(self, session_id: str, channel: str = TEXT) -> dict | None:
        live = self._live.get(session_id, {}).get(channel)
        return {"text": live["text"], "seq": live["seq"]} if live and live["text"] else None

    async def save_thinking(self, session_id: str, text: str) -> None:
        """Save the model's thinking as one `thinking` event and tell the watchers, exactly as the agent loop does for its
        own events. Best effort: if the database refuses the event type (the migration that allows it hasn't been run), the
        failure is logged once and skipped — the live thinking was already shown and the turn is unaffected."""
        text = (text or "").strip()
        if not text:
            return
        if len(text) > MAX_THINKING_CHARS:
            text = text[:MAX_THINKING_CHARS].rstrip() + "…"
        try:
            event = await self._append_event(session_id, "agent", "thinking", {"text": text})
        except Exception as exc:  # noqa: BLE001 — see docstring
            if not self._warned_save:
                self._warned_save = True
                logger.warning("could not save the model's thinking (has db/migrations/0018 been run?): %s", exc)
            return
        self._send(session_id, event)

    def _send(self, session_id: str, payload: dict) -> None:
        try:
            self._broadcast(session_id, payload)
        except Exception:  # noqa: BLE001 — live text is a nicety; it must never be why a model call fails
            logger.warning("live text could not be broadcast for session %s", session_id, exc_info=True)


def _broadcast_via_agent_loop(session_id: str, payload: dict) -> None:
    # Imported here, not at the top: agent_loop imports llm_client, which imports this module.
    from app.services import agent_loop

    agent_loop._broadcast(session_id, payload)  # noqa: SLF001 — the one per-session queue fan-out; see the module docstring


registry = LiveTextRegistry(_broadcast_via_agent_loop)


def snapshot(session_id: str, channel: str = TEXT) -> dict | None:
    return registry.snapshot(session_id, channel)


def is_live_payload(payload: dict) -> bool:
    return payload.get("event_type") in (DELTA, THINKING_DELTA, RESET)


class LiveViewer:
    """One watcher's view of the live text, used by the SSE endpoint. `text_start` / `thinking_start` are what that watcher
    was given up front as snapshots (None if nothing was live when it connected); `first_frames` are those snapshots as SSE
    frames. `frame_for(payload)` turns a broadcast payload into the SSE frame to send — `(name, data)` — or None when the
    watcher must not get it: a delta already inside its snapshot."""

    def __init__(self, text_start: dict | None = None, thinking_start: dict | None = None):
        self._seen = {TEXT: text_start["seq"] if text_start else 0, THINKING: thinking_start["seq"] if thinking_start else 0}
        self.first_frames: list[tuple[str, dict]] = []
        if thinking_start:
            self.first_frames.append(("thinking", {"text": thinking_start["text"], "seq": thinking_start["seq"], "replace": True}))
        if text_start:
            self.first_frames.append(("delta", {"text": text_start["text"], "seq": text_start["seq"], "replace": True}))

    def frame_for(self, payload: dict) -> tuple[str, dict] | None:
        kind = payload.get("event_type")
        if kind == RESET:
            self._seen = {TEXT: 0, THINKING: 0}  # a new reply counts from 1 again
            return ("reset", {})
        if kind in (DELTA, THINKING_DELTA):
            channel = TEXT if kind == DELTA else THINKING
            if payload["seq"] <= self._seen[channel]:
                return None
            return ("delta" if channel == TEXT else "thinking", {"text": payload["text"], "seq": payload["seq"]})
        return None


class LiveSink:
    """What llm_client.call_llm is handed for one streamed call: the verbs it needs, bound to one session."""

    def __init__(self, session_id: str, reg: LiveTextRegistry | None = None):
        self._session_id = session_id
        self._registry = reg or registry

    def delta(self, text: str) -> None:
        self._registry.delta(self._session_id, text)

    def thinking_delta(self, text: str) -> None:
        self._registry.delta(self._session_id, text, THINKING)

    def reset(self) -> None:
        self._registry.reset(self._session_id)

    def end(self) -> None:
        self._registry.end(self._session_id)

    async def save_thinking(self, text: str) -> None:
        await self._registry.save_thinking(self._session_id, text)


def sink(session_id: str) -> LiveSink:
    return LiveSink(session_id)
