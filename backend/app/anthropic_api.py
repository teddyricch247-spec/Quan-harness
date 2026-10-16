"""Anthropic Messages API format adapter — ingress (a caller's Anthropic-
shaped request -> this app's internal Responses-shape input_items/tools)
and egress (internal Responses-shape output -> an Anthropic-shaped
response, non-streamed or streamed).

Added 2026-09-09, reversing an earlier, explicitly-documented decision:
app/anthropic_proxy.py was deleted 2026-08-19, and both app/main.py's and
app/auth.py's docstrings said plainly that no Anthropic-format route
existed and none was planned. This is a genuinely new module, not a
revival of that file — it plugs into the SAME shared internal
architecture (see app/response_api.py's module docstring) as a THIRD
caller_shape, parallel to "chat_completions" and "responses", rather
than reintroducing a separate code path the way the old proxy was.

------------------------------------------------------------------------
Where this sits in the existing architecture
------------------------------------------------------------------------
Every caller of Kael Beta, regardless of which of the three wire shapes
it uses, converges on the exact same internal representation
(response_api.py's Responses-shape input_items and output) before either
pass ever runs, and diverges again only at the very edges — ingress
(turning a caller's request into input_items+tools) and egress (turning
the pipeline's result back into whatever shape the caller used). This
module is that pair of edges for the Anthropic shape specifically:

    Anthropic request (system + messages + tools)
        |
        v  anthropic_to_input() / tools_from_anthropic()
    input_items + tools (Responses shape — the internal canonical shape,
    same as every other caller_shape's ingress produces)
        |
        ... normal two-pass pipeline, completely unaware this request
            ever looked like anything other than the internal shape ...
        |
        v  to_anthropic_message() [non-stream] or AnthropicStreamState
    Anthropic response (content blocks + stop_reason + usage)

Nothing about the two-pass engine, billing, tracing, or either upstream
call changes because a caller used this shape — see
app/two_pass_pipeline.py and app/response_api.py, neither of which
contains Anthropic-specific business logic, only three-way dispatches on
caller_shape at each edge, exactly parallel to the existing two-way ones.

------------------------------------------------------------------------
Ingress: Anthropic's request shape is genuinely different, not just
renamed fields
------------------------------------------------------------------------
Chat Completions and Responses share enough structure that
messages_to_input() in response_api.py is a near-passthrough (see that
function's own docstring). Anthropic's shape is not a near-passthrough:
- `system` is a TOP-LEVEL field on the request, never a message in the
  `messages` array (Anthropic Messages API reference,
  docs.claude.com/en/api/messages, confirmed 2026-09-09: `system` takes
  a string or a list of text blocks, describing "how to behave" — no
  `role` field's ever "system" inside `messages`; the first message must
  be `role: "user"`, or an assistant-prefill message, but never system).
- `content` on a message is EITHER a plain string OR a list of typed
  content blocks (`text`, `image`, `tool_use`, `tool_result`, and, for a
  request that included a caller-supplied `thinking`-block in a prior
  assistant turn being replayed back, `thinking`/`redacted_thinking`)
  — there is no bare "the whole message is one image" shape the way
  some APIs allow; images are always a block inside a content list.
- Tool RESULTS are sent back as a `tool_result` content block inside a
  `user`-role message (Anthropic's convention), never as their own
  top-level message with a dedicated role the way OpenAI's `role: "tool"`
  works. anthropic_to_input() below splits these back out into their own
  `role: "tool"` items — the shape build_chat_completions_body() already
  knows how to place correctly — rather than teaching that function a
  fourth message shape just for this one caller_shape.
- `max_tokens` is REQUIRED on every Anthropic Messages request (no
  default) — this app ignores it regardless, same as every other
  caller-supplied ceiling that isn't the product's own configured one
  (see the top-level README's "OpenAI-compatible, but not caller-tunable"
  section) — accepted for schema compatibility, never read.

------------------------------------------------------------------------
Egress, non-streamed: to_anthropic_message()
------------------------------------------------------------------------
Straightforward reshape of the same internal output every other
caller_shape's non-stream path already reads (responses_output_text_and_
calls(), finish_reason(), usage_from_responses()/billed_client_usage())
into Anthropic's {id, type, role, content: [...], stop_reason, usage}
shape — see that function for the exact field mapping, including the
finish_reason -> stop_reason vocabulary translation (this app's internal
"tool_calls"/"length"/"stop" -> Anthropic's "tool_use"/"max_tokens"/
"end_turn").

------------------------------------------------------------------------
Egress, streamed: AnthropicStreamState
------------------------------------------------------------------------
Anthropic's streaming protocol is stateful and ordered in a way neither
Chat Completions' (flat delta chunks, no open/close bookkeeping) nor this
app's own Responses-shape relay (bare response.*.delta events, no
message_start/content_block_start either — see two_pass_pipeline.py's
consume_pass()) needs to track: every content block must be explicitly
opened (`content_block_start`) before any delta for it, and explicitly
closed (`content_block_stop`) before the next one opens — sending two
deltas for different block types back-to-back with no stop/start between
them is a real protocol violation for a strict Anthropic SDK client, not
just an unconventional detail such a client happens to tolerate.
AnthropicStreamState is the one place that bookkeeping lives — one
instance per streaming request (created in two_pass_pipeline._run_stream(),
same lifetime as ThinkingRelay), tracking which block index is currently
open and of what type, so every call site in two_pass_pipeline.py can
just call `.thinking_delta(text)` / `.text_delta(text)` / `.tool_use_block(...)`
/ `.finish(...)` without needing to know or duplicate the open/close
rules itself.

Thinking titles (see app/thinking_summarizer.py) map onto Anthropic's own
native `thinking` content block type — content_block_start
{"type": "thinking", "thinking": ""} followed by content_block_delta
{"type": "thinking_delta", "thinking": "..."} — which is a closer,
more natively-supported fit than either other caller_shape gets (a real
Anthropic SDK client already renders a `thinking` block specially,
no reasoning_content-adjacent field guessing required).

Tool calls stream as a complete, atomic block (one content_block_start,
one content_block_delta carrying the full arguments JSON as a single
input_json_delta, one content_block_stop) rather than incrementally —
matching the existing precedent for a Responses-shaped caller on this
same wire shape (see consume_pass()'s tool_call_deltas comment: no live
incremental relay exists for anything other than a Chat-Completions-
shaped caller on this upstream), not a new limitation specific to
Anthropic.
"""
import hashlib
import json
import time
import uuid

from . import response_api as ra


# ---------------------------------------------------------------------
# Ingress: Anthropic request -> internal input_items + tools
# ---------------------------------------------------------------------

def _flatten_text_blocks(content) -> str:
    """A `system` field, or a content list that turns out to be pure
    text blocks with nothing else mixed in, collapses to one string —
    this is what lets a plain-text Anthropic request produce the exact
    same simple {"role": ..., "content": "..."} shape a Chat-Completions
    or Responses caller's equivalent plain message already produces,
    rather than always going through the more complex multipart path
    below even when nothing in the message actually needs it."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _is_pure_text(content) -> bool:
    if isinstance(content, str):
        return True
    return all(isinstance(b, dict) and b.get("type") == "text" for b in (content or []))


def _image_block_to_openai_part(block: dict) -> dict | None:
    """Anthropic's image block: {"type": "image", "source":
    {"type": "base64", "media_type": "image/png", "data": "..."}} (or
    {"type": "url", "url": "..."}) -> OpenAI-compatible
    {"type": "image_url", "image_url": {"url": "..."}} — the shape
    build_chat_completions_body() passes straight through as a message
    content part, same as any Chat-Completions caller's own image_url
    part would be. A source type this function doesn't recognize is
    dropped rather than guessed at — silently sending a malformed part
    upstream is worse than silently losing one unrecognized image."""
    source = block.get("source") or {}
    if source.get("type") == "base64" and source.get("media_type") and source.get("data"):
        return {"type": "image_url", "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"}}
    if source.get("type") == "url" and source.get("url"):
        return {"type": "image_url", "image_url": {"url": source["url"]}}
    return None


def _tool_result_content_to_string(content) -> str:
    """A tool_result block's own `content` is itself either a plain
    string or a list of blocks (almost always just text blocks in
    practice) — OpenAI's tool-result message shape wants one plain
    string, so this collapses either form the same way
    _flatten_text_blocks() does for a top-level message, but kept
    separate since a tool_result's content list could in principle
    contain a non-text block (an image tool result) that
    _flatten_text_blocks() would silently drop — this function does the
    same drop, deliberately, but named for what it's actually doing
    here so that choice doesn't read as an oversight."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def anthropic_to_input(body: dict) -> list[dict]:
    """Converts an Anthropic Messages request's `system` + `messages`
    into this app's internal input_items list — see this module's
    docstring for why this is a real conversion, not a near-passthrough
    the way messages_to_input() is for the other two caller shapes.
    Output is always compatible with what build_chat_completions_body()
    already expects to receive as `input_items` (also reused verbatim as
    Chat Completions `messages` — see that function's own docstring),
    so nothing downstream of this function needs to know a request ever
    arrived in Anthropic shape at all."""
    items: list[dict] = []

    system = body.get("system")
    if system:
        items.append({"role": "system", "content": _flatten_text_blocks(system)})

    for msg in body.get("messages") or []:
        role = msg.get("role")
        content = msg.get("content")

        if _is_pure_text(content):
            items.append({"role": role, "content": _flatten_text_blocks(content)})
            continue

        # Mixed/non-text content: split into (a) an assistant/user
        # message carrying text + image + tool_use parts, in original
        # order, and (b) one separate role:"tool" item per tool_result
        # block, pulled OUT of a user message entirely — see this
        # module's docstring for why tool_result can't stay inline the
        # way Anthropic itself sends it.
        parts = []
        tool_calls = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"type": "text", "text": block.get("text", "")})
            elif btype == "image":
                part = _image_block_to_openai_part(block)
                if part:
                    parts.append(part)
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "type": "function",
                    "function": {"name": block.get("name"), "arguments": json.dumps(block.get("input") or {})},
                })
            elif btype == "tool_result":
                items.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id"),
                    "content": _tool_result_content_to_string(block.get("content")),
                })
            # thinking / redacted_thinking blocks (a caller replaying
            # back a prior assistant turn verbatim, thinking included)
            # are intentionally dropped here, not passed through: this
            # app's own upstream models have no concept of "resume a
            # prior thinking block," and forwarding one as plain text
            # would misrepresent internal reasoning neither upstream
            # model actually produced as its own.

        if parts or tool_calls:
            entry: dict = {"role": role, "content": parts if parts else ""}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            items.append(entry)

    return items


def tools_from_anthropic(tools: list[dict] | None) -> list[dict] | None:
    """Anthropic's tool shape: {"name", "description", "input_schema"}.
    This app's internal (Responses-shape) tool shape:
    {"type": "function", "name", "description", "parameters"} — see
    response_api.tools_to_responses() for the equivalent conversion from
    Chat-Completions-shaped tools. `input_schema` and `parameters` are
    the same JSON Schema object under two different field names; nothing
    else about the schema itself needs to change."""
    if not tools:
        return None
    converted = []
    for t in tools:
        if not isinstance(t, dict) or "input_schema" not in t:
            continue  # a built-in/server tool type (e.g. "computer_20250124") — no equivalent upstream, silently dropped rather than sent as malformed
        flat = {"type": "function", "name": t.get("name"), "parameters": t.get("input_schema")}
        if "description" in t:
            flat["description"] = t["description"]
        converted.append(flat)
    return converted or None


# ---------------------------------------------------------------------
# Egress, non-streamed
# ---------------------------------------------------------------------

_STOP_REASON_MAP = {"tool_calls": "tool_use", "length": "max_tokens", "stop": "end_turn"}


def to_anthropic_message(data: dict, slug: str, billed_usage: dict | None = None) -> dict:
    """Full reshape of a completed (non-stream) internal Responses object
    into an Anthropic Messages response. `billed_usage`, when given,
    overrides data["usage"] in the output — same reasoning as
    response_api.to_chat_completion()'s identical parameter; see
    billed_client_usage()'s docstring for why the raw upstream usage on
    `data` is never what a two-pass caller should see."""
    text, calls = ra.responses_output_text_and_calls(data.get("output") or [])
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for call in calls:
        fn = call.get("function", {})
        try:
            call_input = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            call_input = {}
        content.append({"type": "tool_use", "id": call.get("id"), "name": fn.get("name"), "input": call_input})
    if not content:
        content.append({"type": "text", "text": ""})

    has_calls = bool(calls)
    usage_norm = billed_usage if billed_usage is not None else ra.usage_from_responses(data.get("usage") or {})
    return {
        "id": data.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": slug,
        "content": content,
        "stop_reason": _STOP_REASON_MAP.get(ra.finish_reason(data, has_calls), "end_turn"),
        "stop_sequence": None,
        "usage": {"input_tokens": usage_norm.get("prompt_tokens", 0), "output_tokens": usage_norm.get("completion_tokens", 0)},
    }


# ---------------------------------------------------------------------
# Egress, streamed
# ---------------------------------------------------------------------

def _sse(event: str, data: dict) -> str:
    """Anthropic's own streaming format names the event on its own line
    in addition to embedding "type" inside the data payload (both are
    required — confirmed against docs.claude.com/en/docs/build-with-
    claude/streaming, 2026-09-09) — unlike this app's Responses-shape
    relay, which only sometimes bothers with the `event:` line (see
    consume_pass()) since real OpenAI/DeepSeek clients mostly key off
    `data`'s own "type" field instead. Anthropic clients expect both."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class AnthropicStreamState:
    """Owns the open/close bookkeeping Anthropic's streaming protocol
    requires — see this module's docstring, "Egress, streamed" section,
    for why this needs to be stateful at all where the other two caller
    shapes don't. One instance per streaming request, created in
    two_pass_pipeline._run_stream() alongside ThinkingRelay, with the
    same whole-request lifetime — thinking titles from BOTH passes flow
    into the SAME open `thinking` block (or a fresh one, if a prior one
    already had to be closed to make room for real text — see
    thinking_delta() below), for the same "no seam at the pass boundary"
    reason ThinkingRelay itself carries one `history` across both
    passes."""

    def __init__(self, message_id: str, slug: str):
        self.message_id = message_id
        self.slug = slug
        self._index = -1
        self._open_type: str | None = None  # None | "thinking" | "text" | "tool_use"
        self._started = False
        # Text of the thinking block currently open; only used to make its
        # closing signature (see _close_open_block()).
        self._thinking_text = ""

    def message_start(self, input_tokens: int) -> str:
        self._started = True
        return _sse("message_start", {
            "type": "message_start",
            "message": {
                "id": self.message_id, "type": "message", "role": "assistant", "model": self.slug,
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
            },
        })

    def _close_open_block(self) -> str:
        s = ""
        if self._open_type == "thinking":
            # Anthropic's own streams end every thinking block with a
            # signature_delta before content_block_stop, and SDK clients
            # (and anything that stores the block to replay it) expect one.
            # Kael's titles are not real chain-of-thought and nothing here
            # verifies a signature (a replayed thinking block is dropped on
            # the way in, see this module's ingress), so the value is an
            # opaque, non-empty, deterministic token: a hash of the block's
            # own text.
            signature = hashlib.sha256(self._thinking_text.encode("utf-8", errors="ignore")).hexdigest()
            s += _sse("content_block_delta", {"type": "content_block_delta", "index": self._index, "delta": {"type": "signature_delta", "signature": signature}})
            self._thinking_text = ""
        s += _sse("content_block_stop", {"type": "content_block_stop", "index": self._index})
        self._open_type = None
        return s

    def thinking_delta(self, text: str) -> str:
        """One thinking title or filler word (see app/thinking_summarizer.py)
        becomes one content_block_delta on an open "thinking" block,
        opening it first if this is the very first one."""
        out = ""
        if self._open_type != "thinking":
            if self._open_type is not None:
                out += self._close_open_block()
            self._index += 1
            self._open_type = "thinking"
            self._thinking_text = ""
            out += _sse("content_block_start", {"type": "content_block_start", "index": self._index, "content_block": {"type": "thinking", "thinking": ""}})
        self._thinking_text += text
        out += _sse("content_block_delta", {"type": "content_block_delta", "index": self._index, "delta": {"type": "thinking_delta", "thinking": text}})
        return out

    def text_delta(self, text: str) -> str:
        out = ""
        if self._open_type != "text":
            if self._open_type is not None:
                out += self._close_open_block()
            self._index += 1
            self._open_type = "text"
            out += _sse("content_block_start", {"type": "content_block_start", "index": self._index, "content_block": {"type": "text", "text": ""}})
        out += _sse("content_block_delta", {"type": "content_block_delta", "index": self._index, "delta": {"type": "text_delta", "text": text}})
        return out

    def tool_use_block(self, tool_id: str, name: str, arguments_json: str) -> str:
        """Emitted whole, not incrementally — see this module's docstring
        for why (no live per-token relay exists for tool-call arguments
        on this upstream for any caller shape other than
        Chat-Completions). One input_json_delta carrying the complete
        arguments string is still spec-valid: Anthropic's own protocol
        never requires more than one delta per block, only that at least
        the block's start/stop wrap whatever deltas there are."""
        out = ""
        if self._open_type is not None:
            out += self._close_open_block()
        self._index += 1
        self._open_type = "tool_use"
        out += _sse("content_block_start", {"type": "content_block_start", "index": self._index, "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}}})
        out += _sse("content_block_delta", {"type": "content_block_delta", "index": self._index, "delta": {"type": "input_json_delta", "partial_json": arguments_json}})
        out += self._close_open_block()
        return out

    def finish(self, stop_reason: str, output_tokens: int, input_tokens: int | None = None) -> str:
        """Closes whatever's still open (a request with genuinely no
        content at all — the same "draft produced nothing reviewable"
        edge case two_pass_pipeline.py already handles — never opened a
        block in the first place, so there's nothing to close in that
        case; guarded below rather than assumed), then message_delta
        (the only place stop_reason and final output_tokens are ever
        sent — Anthropic never repeats them on message_start) and
        message_stop."""
        out = ""
        if self._open_type is not None:
            out += self._close_open_block()
        # message_start goes out at the first thinking title, long before the
        # draft pass has reported its prompt tokens, so it can only carry 0.
        # The real (billed) input count is known by now; Anthropic's
        # message_delta usage may carry input_tokens, and the SDKs' stream
        # accumulators overwrite message_start's value with it. Without this
        # a streaming Messages caller would see input_tokens: 0 on every request.
        usage = {"output_tokens": output_tokens}
        if input_tokens is not None:
            usage["input_tokens"] = input_tokens
        out += _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": _STOP_REASON_MAP.get(stop_reason, "end_turn"), "stop_sequence": None}, "usage": usage})
        out += _sse("message_stop", {"type": "message_stop"})
        return out
