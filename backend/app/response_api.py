"""Shared wire-format adapter. Pure functions only, no I/O — see
app/two_pass_pipeline.py for the actual upstream calls this module's
output feeds, and for why that split (pure/testable vs. I/O) exists.

app/kael_pipeline.py (Kael Beta, DeepSeek V4.1 Flash for draft and critic,
via OpenRouter — its only product left, see below) speaks Chat Completions
on the wire for BOTH passes of its two-pass pipeline, but this module
still standardizes on ONE canonical shape *internally* — the Responses
API shape — for output items, usage, and finish/status, regardless of
which shape the caller used to reach us or which shape the upstream
provider actually spoke. This module is the one place that owns the
conversion at every boundary, so two_pass_pipeline.py's orchestration
logic (retry/timeout/fallback handling, billing, tracing) only ever
reads one shape's fields rather than branching per-provider — see the
top-level README's "Why one shared adapter" section.

Architecture, end to end:

    caller request (Chat Completions OR Responses shape)
        |
        v  messages_to_input() / caller's own `input`, tools_to_responses()
    input items (Responses shape — the internal canonical shape)
        |
        v  build_chat_completions_body() -> POST {base}/v1/chat/completions
    draft response, Chat-Completions shape over the wire, converted
    immediately via chat_completion_to_responses_shape() /
    cc_accumulator_to_responses_shape() into the same internal shape
        |
        v  responses_output_text_and_calls() -> (text, tool_calls)
    render_draft_for_critic() -> critic input item appended
        |
        v  build_chat_completions_body() -> POST {base}/v1/chat/completions  <- pass 2, same conversion as above
        |
        v  reshape(): stays Responses-shape for a Responses caller,
        |             to_chat_completion() for a Chat-Completions caller
    caller response (whichever shape the caller's request used)

Two DIFFERENT things are both sometimes called "Responses shape" in this
file, worth keeping straight: (1) the internal canonical representation
every pass's result gets normalized into before anything else touches
it, which every function above operates on; and (2) OpenAI/DeepSeek's
Responses API as a literal upstream WIRE format, which this module used
to also speak (build_responses_body() -> POST {base}/v1/responses) for
Aura Beta's entire upstream and, before 2026-08-30, Kael Beta's too.
(2) is gone — deleted 2026-09-08 along with the rest of Aura Beta, once
no PassConfig anywhere could construct that path anymore (see
two_pass_pipeline.py's module docstring and the top-level README's
removal note). (1) is unaffected and not going anywhere: it's why
billing.py, the tracing calls, and reshape()/to_chat_completion() below
can all stay written against one shape's fields even though the
upstream wire format changed twice (DeepSeek Responses API -> GLM direct
Chat Completions -> OpenRouter Chat Completions) under them without any
of those three needing to change. If a future product needs a literal
Responses-API upstream again, that's a new function here plus a new
branch in two_pass_pipeline._post_upstream(), added back deliberately —
not something to leave half-wired in the meantime.

Field names below (reasoning.effort in the old upstream body-builder's
history, input_tokens/output_tokens, input_tokens_details.cached_tokens,
output_tokens_details.reasoning_tokens — all still real fields on the
INTERNAL canonical shape, meaning (1) above, regardless of upstream) come
from DeepSeek's and OpenAI's own current docs, not assumption — see each
function's docstring for the specific source where it matters.

------------------------------------------------------------------------
Chat Completions upstream, Kael Beta's only wire format since 2026-08-30
------------------------------------------------------------------------
Kael Beta's upstream moved from DeepSeek's deepseek-v4-flash (Responses
API, both passes) to Z.ai's glm-5.3-flash direct (Chat Completions only,
both passes, confirmed against Z.ai's own OpenAPI spec at
docs.z.ai/api-reference/llm/chat-completion: the one documented endpoint
is POST /paas/v4/chat/completions, no /responses path exists) on
2026-08-30, then to OpenRouter on 2026-08-31 — still Chat Completions
only, but now TWO different models instead of one shared between both
passes: z-ai/glm-5.3-flash (draft) and deepseek/deepseek-v4-flash-0731
(critic), both reached through OpenRouter rather than either provider's
own platform, both pinned to the Relace provider (see
models/kael/config.py's draft_provider_routing/critic_provider_routing).
That is the history; since 2026-10-05 both passes are
deepseek/deepseek-v4.1-flash, routed speed-first and not pinned.

build_chat_completions_body() is the outbound half (Responses-shaped
input_items -> a Chat-Completions-shaped request body — OpenRouter's
unified shape, or GLM's native fields directly, see that function's own
docstring for the branch), and chat_completion_to_responses_shape() /
the cc_accumulator_* trio are the inbound half (a chat.completion or
stream of chat.completion.chunks -> the same Responses-shaped dict
responses_output_text_and_calls(), usage_from_responses(),
finish_reason(), and reshape() already know how to read). See
two_pass_pipeline._post_upstream() / consume_pass() for the only two
places that call into this section.

Message ordering at this edge is NOT the convention the Responses-shape
side above uses, and changed again 2026-10-01. Chat Completions has no
separate `instructions` field — everything is one flat `messages` list —
so build_chat_completions_body() below orders it explicitly:

    1. system_identity (the master prompt) — FIRST, always.
    2. The caller's own conversation, exactly as prepare_input_items()
       produced it: caller system/developer content wrapped in
       <caller_system_prompt_{boundary}>, the user/assistant/tool turns
       untouched, and the Kael-context message
       (<kael_context_{boundary}>, see build_kael_context_message())
       last.
    3. Trailing messages — the difficulty-router instruction on the
       draft pass, the review prompt on the critic pass.

From 2026-08-30 to 2026-10-01 system_identity sat LAST instead, so its
non-overridable rules would be adjacent to generation. The master prompt
now carries its own authority by explicitly ranking every other layer
(see models/kael/config.py's comment above system_identity for the full
reasoning and the cost of the move), which is what lets it go first: the
one fully static block becomes a prefix identical across every request,
and per-request material (the date, and later skills) stays at the end
where it can't disturb that prefix.
"""
from __future__ import annotations

import json
import re

from . import identity_guard, provider_routing


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------

class UpstreamCallError(Exception):
    """Raised by the pipelines' own HTTP-call wrappers (not defined in
    this module — each pipeline still owns its httpx client and retry/
    timeout policy, since those differ slightly between DeepSeek and
    OpenAI). Kept here only as the common type both pipelines'
    exception handling can catch, so a shared `except` clause is
    possible if orchestration code ever wants one."""

    def __init__(self, http_status: int, log_message: str, client_payload: dict):
        self.http_status = http_status
        self.log_message = log_message
        self.client_payload = client_payload
        super().__init__(log_message)


def missing_key_error(provider: str) -> dict:
    return {"error": {"message": f"Server is missing its {provider.upper()}_API_KEY.", "type": "server_error"}}


def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text[:2000]}


# ---------------------------------------------------------------------
# Chat Completions -> Responses (inbound conversion, used once at the
# edge when the caller used /v1/chat/completions instead of
# /v1/responses)
# ---------------------------------------------------------------------

def messages_to_input(messages: list[dict] | None) -> list[dict]:
    """Chat Completions `messages` and Responses `input` are both "a
    list of role+content items" for plain text turns — a system/user/
    assistant message with string content is already a valid Responses
    input item as-is, no reshaping needed. This is deliberately a thin
    pass-through, not a rewrite: it exists as a named conversion step
    (not an inline `messages or []`) so every place that needs this
    conversion goes through one function, and so the day multimodal
    Chat-Completions content (image_url parts, etc.) needs real
    translation into Responses' input_text/input_image content-part
    shape, there's exactly one function to change."""
    return list(messages) if messages else []


def _responses_content_to_chat(content):
    """Responses message `content` -> Chat Completions `content`. A string
    stays a string. A list of parts becomes one string when it is text only
    (input_text / output_text / text / refusal, joined with no separator like
    anthropic_api._flatten_text_blocks), or a Chat-style parts list when an
    image is mixed in (input_image -> image_url). Parts with no Chat
    equivalent (input_file, audio, ...) are dropped."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[dict] = []
    has_image = False
    for p in content:
        if isinstance(p, str):
            parts.append({"type": "text", "text": p})
        elif isinstance(p, dict):
            ptype = p.get("type")
            if ptype in ("input_text", "output_text", "text") and isinstance(p.get("text"), str):
                parts.append({"type": "text", "text": p["text"]})
            elif ptype == "refusal" and isinstance(p.get("refusal"), str):
                parts.append({"type": "text", "text": p["refusal"]})
            elif ptype == "input_image":
                url = p.get("image_url")
                if isinstance(url, dict):
                    url = url.get("url")
                if isinstance(url, str) and url:
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                    has_image = True
            elif ptype == "image_url" and p.get("image_url"):
                parts.append(p)
                has_image = True
    if has_image:
        return parts
    return "".join(p["text"] for p in parts)


def responses_input_to_messages(raw_input, instructions=None) -> list[dict]:
    """Responses `input` (+ the top-level `instructions` field) -> the chat
    `messages` list this app uses internally (the same shape
    anthropic_to_input() and messages_to_input() produce, and what
    build_chat_completions_body() sends upstream as-is).

    Real Responses clients (the OpenAI SDKs, Agents SDK, Codex) send typed
    items, not bare role/content pairs: content parts like
    {"type": "input_text"}, function_call / function_call_output items for
    tool round-trips, reasoning items. Passed through raw they reach the
    upstream chat endpoint as malformed messages. And `instructions` (the
    Responses system prompt) was read nowhere, so it was silently dropped.

    - `instructions` -> a leading system message (prepare_input_items wraps
      it as the caller's system prompt like any other).
    - string `input` -> one user message.
    - message items -> {role, content}; extra keys on chat-style items
      (tool_calls, tool_call_id, name) are kept, so a caller that sends
      chat-shaped items to this route still works.
    - function_call -> assistant tool_calls entry, merged into the
      immediately preceding assistant message (parallel calls share one).
    - function_call_output -> a `tool` message keyed by call_id.
    - reasoning, item_reference and any other item type are skipped.
    """
    msgs: list[dict] = []
    if isinstance(instructions, str) and instructions.strip():
        msgs.append({"role": "system", "content": instructions})
    if isinstance(raw_input, str):
        msgs.append({"role": "user", "content": raw_input})
        return msgs
    for item in raw_input or []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "function_call":
            args = item.get("arguments")
            if not isinstance(args, str):
                args = json.dumps(args if args is not None else {})
            call = {"id": item.get("call_id") or item.get("id"), "type": "function", "function": {"name": item.get("name"), "arguments": args}}
            prev = msgs[-1] if msgs else None
            if prev is not None and prev.get("role") == "assistant":
                prev.setdefault("tool_calls", []).append(call)
            else:
                msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
        elif itype == "function_call_output":
            out = item.get("output")
            if isinstance(out, list):
                out = _responses_content_to_chat(out)
            elif out is not None and not isinstance(out, str):
                out = json.dumps(out)
            msgs.append({"role": "tool", "tool_call_id": item.get("call_id"), "content": out or ""})
        elif itype in (None, "message") and item.get("role"):
            msg = {k: v for k, v in item.items() if k not in ("type", "id", "status")}
            msg["content"] = _responses_content_to_chat(item.get("content"))
            if item.get("role") == "assistant" and "content" in item and item["content"] is None:
                msg["content"] = ""
            msgs.append(msg)
    return msgs


def tools_to_responses(tools: list[dict] | None) -> list[dict] | None:
    """Chat Completions wraps a function tool as
    {"type": "function", "function": {"name", "description",
    "parameters"}}; Responses flattens it to
    {"type": "function", "name", "description", "parameters"} directly
    on the tool object, no nested "function" key. Non-function tool
    types (unused by either product today — no built-in tools are
    exposed) pass through unchanged rather than being dropped, so an
    unrecognized tool shape fails loudly upstream instead of silently
    vanishing."""
    if tools is None:
        return None
    flattened = []
    for t in tools:
        if isinstance(t, dict) and t.get("type") == "function" and "function" in t:
            fn = t["function"] or {}
            flat = {"type": "function", "name": fn.get("name"), "parameters": fn.get("parameters")}
            if "description" in fn:
                flat["description"] = fn["description"]
            flattened.append(flat)
        else:
            flattened.append(t)
    return flattened


def build_kael_context_message(request_time, boundary: str, extra_sections: list[str] | None = None) -> dict:
    """The Kael-context message: one `system` item carrying everything
    Kael itself wants the model to know about THIS request, as opposed to
    anything the caller supplied — wrapped in
    <kael_context_{boundary}>...</kael_context_{boundary}>, the tag the
    master prompt (models/kael/config.py's system_identity) names and
    ranks directly under itself, above the caller's own instructions.
    Added 2026-10-01.

    Today it carries one thing, the real current date (text unchanged
    from when it was a bare system sentence; see prepare_input_items()'s
    point 2 for why the date is said at all and why it lives here at the
    end of the request rather than inside system_identity). This is also
    the seam for what's coming: `extra_sections` — each a ready-to-send
    string, appended after the date as its own paragraph — is where a
    pre-draft step that attaches skills or reference material for this
    request hands them over, so they arrive inside a tag the model has
    already been told means "from Kael, not from the caller." Nothing
    passes any yet. Blank or non-string entries are skipped rather than
    emitted as empty paragraphs.

    `boundary` is the same per-request random token every other tag
    this request uses is built from. The tag name is not secret in the
    sense a caller-content wrapper's is (this block's own contents are
    Kael's, not attacker-influenced), but it stays unpredictable for the
    other direction: it is what stops text inside a user turn or a
    caller prompt from imitating a Kael-context block, since the
    imitation would need the real suffix to match."""
    tag = f"kael_context_{boundary}"
    sections = [
        f"Today's real-world date is {request_time.strftime('%A, %B %-d, %Y')} (UTC). "
        "Use this as the actual current date for any date-relative reasoning, "
        "deadline math, or judgment about what's recent versus outdated — do not "
        "assume the current date is whenever your own training data happens to end."
    ]
    for extra in extra_sections or []:
        if isinstance(extra, str) and extra.strip():
            sections.append(extra)
    return {"role": "system", "content": f"<{tag}>\n" + "\n\n".join(sections) + f"\n</{tag}>"}


def prepare_input_items(input_items: list[dict], request_time, boundary: str, kael_context_sections: list[str] | None = None) -> list[dict]:
    """The one place a caller's raw input items get touched before either
    pass ever sees them — called once, from
    two_pass_pipeline.run_pipeline(), which is the single point every
    entry path (a chat_completions- or responses-shaped caller alike)
    already funnels through before either pass is built. Both the
    draft AND the critic inherit the result automatically and
    identically (the critic builds its own input as
    `list(input_items) + [...]` — see two_pass_pipeline._critic_body —
    from whatever this function already returned).

    Two things happen here, both added 2026-08-24 for the same underlying
    reason: a caller of this API is very often not a human typing in a
    chat window. It's frequently a third-party developer's own
    application, agent harness, or coding tool (this product is sold as
    a developer API, not a consumer chat product — see the top-level
    README's "What this project is" framing) — which may have its own
    system prompt defining its own name, persona, and rules for ITS end
    users, layered on top of whatever this API itself tells the model.
    Neither of the two things below changes what the model is TOLD to do
    with any of this — that's models/kael/config.py's system_identity
    (passed as its own explicit, structurally separate parameter to
    build_chat_completions_body(), not mixed into `input_items` — see
    that function's own docstring), which is where the actual
    identity-layering/precedence rules live. This function only makes
    the raw material those rules operate on unambiguous:

    1. Any caller-supplied `system` or `developer` role item (OpenAI's
       Responses API treats the two as equally privileged — confirmed
       directly against developers.openai.com/api/reference's `role`
       field docs, 2026-08-24: "Instructions given with the developer or
       system role take precedence over instructions given with the
       user role") gets its string content wrapped in
       <caller_system_prompt_{boundary}> tags — `boundary` (added
       2026-09-13) is a fresh, unpredictable-from-outside hex token
       two_pass_pipeline.run_pipeline() generates once per request (via
       secrets.token_hex()) and passes in here, the same value it also
       threads into critic.build_critic_message() for that function's
       own <draft_{boundary}> wrapper — see that function's docstring
       for the full threat model. Before this, the tag was the static
       string `<caller_system_prompt>`, which meant a caller whose OWN
       system/developer content happened to contain the literal text
       `</caller_system_prompt>` (directly, or via end-user content that
       content flowed into it) could read as closing the block early,
       with whatever followed treated as this app's own platform-level
       text rather than the caller's. A per-request random suffix means
       there's no fixed string to predict and close in advance. This
       gives the model an explicit, textual answer to "whose
       instructions are these" instead of leaving it to infer that
       purely from field-level structure — the same reasoning behind
       wrapping any less-trusted or differently-scoped block of
       instructions in a named tag rather than leaving it to blend into
       the surrounding text. Both content shapes are wrapped as of
       2026-10-01: a string gets the tags around it; a list of content
       parts (OpenAI's own `[{"type": "text", ...}]` form for a system
       message — also what clients that attach cache-control hints to a
       system prompt send) keeps every original part untouched and gets
       an opening and a closing text part added around them, so nothing
       is reshaped or dropped. Before 2026-10-01 a list passed through
       unwrapped, which was a harmless gap while "unwrapped" only meant
       "unlabeled"; it is not harmless now that the master prompt
       (models/kael/config.py) treats any system message NOT inside a
       caller tag as Kael's own — an unwrapped caller prompt would have
       been mislabeled as Kael's. An item with no content, or content of
       any other shape, is left untouched.

    2. A final `system` item is appended: the Kael-context message (see
       build_kael_context_message()), a <kael_context_{boundary}> block
       stating the real current date — and, where the caller of this
       function passes them in `kael_context_sections`, any further
       per-request Kael information (skills, reference material).
       Reworked 2026-10-01 from a bare date sentence into a tagged block
       so the master prompt (models/kael/config.py) can tell the model,
       by tag, that this text is Kael's own and not the caller's — the
       clear Kael-versus-caller distinction attaching skills requires.
       The date itself is still said nowhere else in this app: without
       it every request gave the model zero grounding for date-relative
       reasoning ("next month," "is X still current," "how long ago was
       Y"), so a model's default is to reason as if the present moment
       IS its own training cutoff. Still deliberately NOT folded into
       system_identity, which is otherwise 100% static text: baking in a
       value that changes daily would invalidate the shared cached
       prefix once a day for every customer. The date belongs at the END
       of the request, where it can't disturb anything stable before it
       — which, since 2026-10-01, includes system_identity itself, now
       FIRST (see build_chat_completions_body()).
    """
    tag = f"caller_system_prompt_{boundary}"
    prepared: list[dict] = []
    for item in input_items:
        if isinstance(item, dict) and item.get("role") in ("system", "developer"):
            content = item.get("content")
            if isinstance(content, str):
                prepared.append({**item, "content": f"<{tag}>\n{content}\n</{tag}>"})
                continue
            if isinstance(content, list):
                # Same wrapper-part type the list already uses, so a
                # Responses-style `input_text` list isn't handed a
                # Chat-Completions-style `text` part it never contained.
                part_type = "input_text" if any(isinstance(p, dict) and p.get("type") == "input_text" for p in content) else "text"
                prepared.append({**item, "content": [
                    {"type": part_type, "text": f"<{tag}>\n"},
                    *content,
                    {"type": part_type, "text": f"\n</{tag}>"},
                ]})
                continue
        prepared.append(item)
    prepared.append(build_kael_context_message(request_time, boundary, kael_context_sections))
    return prepared


# ---------------------------------------------------------------------
# Responses -> Chat Completions (outbound conversion, used once at the
# edge when the caller used /v1/chat/completions)
# ---------------------------------------------------------------------

def function_call_item_to_tool_call(item: dict) -> dict:
    return {
        "id": item.get("call_id"),
        "type": "function",
        "function": {"name": item.get("name"), "arguments": item.get("arguments", "")},
    }


def responses_output_text_and_calls(output_items: list) -> tuple[str | None, list[dict]]:
    """Walks a Responses `output` array (present on both a non-stream
    response and the terminal response.completed/incomplete event's
    embedded `response` object) and pulls out (assistant text, function
    calls). `reasoning` items are skipped — they're DeepSeek/OpenAI's
    internal chain-of-thought record, not caller-visible content, and
    never contribute to `text`. Both text and calls can be non-empty at
    once (a model can narrate before calling a tool); returns
    (None, []) if there's genuinely nothing usable (e.g. only a
    reasoning item, which happens if a call gets cut off by a token
    limit before producing output)."""
    text_parts, calls = [], []
    for item in output_items or []:
        item_type = item.get("type")
        if item_type == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text" and part.get("text"):
                    text_parts.append(part["text"])
        elif item_type == "function_call":
            calls.append(function_call_item_to_tool_call(item))
    text = "".join(text_parts) if text_parts else None
    return text, calls


def finish_reason(data: dict, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_calls"
    return "length" if data.get("status") == "incomplete" else "stop"


# ---------------------------------------------------------------------
# Usage accounting
# ---------------------------------------------------------------------

def usage_from_responses(usage: dict) -> dict:
    """Responses usage shape (both DeepSeek and OpenAI, confirmed
    against DeepSeek's /guides/responses_api/ docs and OpenAI's own
    Responses API reference) is
    {input_tokens, output_tokens, total_tokens,
     input_tokens_details: {cached_tokens},
     output_tokens_details: {reasoning_tokens}} — nothing like Chat
    Completions' prompt_tokens/completion_tokens/prompt_tokens_details
    naming. Normalized here into ONE internal shape
    ({prompt_tokens, completion_tokens, cached_tokens, total_tokens})
    that the rest of the app (billing.py, supabase_client.log_usage)
    reads, so neither of them needs to know or care that the wire shape
    changed. reasoning_tokens is intentionally not carried into this
    shape — it's a subset of output_tokens, not additional tokens, and
    nothing downstream needs it broken out separately today."""
    details_in = usage.get("input_tokens_details") or {}
    return {
        "prompt_tokens": usage.get("input_tokens", 0) or 0,
        "completion_tokens": usage.get("output_tokens", 0) or 0,
        "cached_tokens": details_in.get("cached_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
    }


def sum_usage(*usages: dict) -> dict:
    out = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "total_tokens": 0}
    for u in usages:
        for k in out:
            out[k] += u.get(k, 0) or 0
    return out


def client_usage(u: dict) -> dict:
    """Internal canonical shape -> the shape actually put on the wire
    to a Chat-Completions-shaped caller's `usage` field. Keeps
    DeepSeek's own `prompt_cache_hit_tokens` naming (rather than
    OpenAI's nested prompt_tokens_details.cached_tokens) because that's
    what this app has always emitted and existing integrations built
    against it — every upstream's usage gets normalized through
    usage_from_responses() first, regardless of provider, before ever
    reaching this function, so the naming choice here is about API
    stability for existing callers, not about which provider happened
    to be involved."""
    return {
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "total_tokens": u.get("total_tokens", 0),
        "prompt_cache_hit_tokens": u.get("cached_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Injected-prompt overhead (added 2026-10-03, owner decision).
#
# The first (draft) pass carries text Kael itself adds to every request: the
# master prompt (system_identity, FIRST in the message list), the caller-prompt
# wrapper tags, the <kael_context> block (date, later skills) and the trailing
# difficulty-router instruction. The upstream counts all of it in
# prompt_tokens, so without this a one-word message bills thousands of input
# tokens the caller never sent. Callers are billed, and shown, input minus
# that injected text. Output is untouched.
#
# The injected text is fixed English prose, so its token count depends only
# on its length, not on what the caller sent (images, JSON, other languages).
# It is therefore estimated from its own character count at a fixed
# tokens-per-char rate rather than scaled off the caller's request.
#
# Calibrated 2026-10-03 against real traffic: two draft-only requests with
# tiny user messages ("Hi, who are you?", "Who made you?", 2026-10-02) were
# logged by the upstream at 3123 and 3117 prompt tokens, for 14,604
# characters of injected text (master prompt + context block + router
# instruction) -> about 0.212 tokens per character. Re-measure with the same
# kind of tiny request whenever the master prompt or router prompt changes a
# lot; the estimate tracks edits to the text automatically, but the ratio
# itself is only as good as that sample.
# ---------------------------------------------------------------------------
INJECTED_TOKENS_PER_CHAR = 0.212


def text_chars(content) -> int:
    """Characters of text in a message `content` (string, or list of parts
    where only text-bearing parts count)."""
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                total += len(part["text"])
        return total
    return 0


def injected_input_chars(raw_items: list[dict], prepared_items: list[dict], system_identity: str, trailing_messages: list[dict] | None) -> tuple[int, int]:
    """(prefix_chars, total_chars) of text Kael injected into the draft
    request. prefix_chars is system_identity alone: it sits first, so it is
    the part a cache hit covers before anything else. total_chars adds the
    caller-prompt wrapper tags (prepared minus raw, item by item), every item
    prepare_input_items appended past the caller's own (the context block),
    and the trailing router message."""
    prefix = len(system_identity or "")
    total = prefix
    for i, item in enumerate(prepared_items):
        if i < len(raw_items):
            total += max(text_chars((item or {}).get("content")) - text_chars((raw_items[i] or {}).get("content")), 0)
        else:
            total += text_chars((item or {}).get("content"))
    for msg in trailing_messages or []:
        total += text_chars((msg or {}).get("content"))
    return prefix, total


def estimate_injected_tokens(chars: int) -> int:
    return max(int(round(chars * INJECTED_TOKENS_PER_CHAR)), 0)


def remove_injected_input(usage_norm: dict, overhead_tokens: int, prefix_tokens: int) -> dict:
    """Draft-pass usage with Kael's injected input taken out. prompt_tokens
    loses the whole overhead; cached_tokens loses only what the cache hit
    spent on the injected prefix (system_identity, first in the request).
    Never negative, and cached never exceeds prompt. Outputs unchanged."""
    prompt = usage_norm.get("prompt_tokens", 0) or 0
    cached = usage_norm.get("cached_tokens", 0) or 0
    completion = usage_norm.get("completion_tokens", 0) or 0
    new_prompt = max(prompt - max(overhead_tokens, 0), 0)
    new_cached = min(max(cached - max(prefix_tokens, 0), 0), new_prompt)
    return {**usage_norm, "prompt_tokens": new_prompt, "cached_tokens": new_cached, "total_tokens": new_prompt + completion}


def billed_client_usage(draft_usage_norm: dict, last_usage_norm: dict) -> dict:
    """What gets shown to the CALLER in the response's `usage` field.

    Bug fix (2026-08-20): this used to just be whatever the *last*
    upstream call's own usage object said — which for a two-pass
    request means the critic call's self-reported `input_tokens`, and
    that number includes the entire draft response plus the critic
    instructions baked into the critic's own prompt. A caller who sent
    one 40-token message could see `usage.prompt_tokens` in the
    thousands, wildly out of proportion to what they actually sent —
    and worse, a number that didn't match what they were actually
    charged, since app/billing.py has always billed on a different
    rule (first-call input, last-call output — see billing.py's module
    docstring). The bill and the receipt disagreeing is worse than
    either being wrong alone.

    Fixed to mirror billing.py's rule exactly: input (+ cache) comes
    from the FIRST call (the draft — what the caller's own conversation
    actually cost to read), output comes from the LAST call that
    produced the final answer (the critic, or the draft itself on a
    fallback-to-draft path where the critic never ran or never
    finished). Nothing from "the middle" is in here because there is no
    middle in a two-pass pipeline — draft and critic ARE first and
    last. See app/billing.py's charge_for_request() — this must always
    compute the same {prompt_tokens, cached_tokens} half and the same
    completion_tokens half that billing charges for, or a customer's
    invoice and their API response tell two different stories."""
    return {
        "prompt_tokens": draft_usage_norm.get("prompt_tokens", 0),
        "completion_tokens": last_usage_norm.get("completion_tokens", 0),
        "cached_tokens": draft_usage_norm.get("cached_tokens", 0),
        "total_tokens": draft_usage_norm.get("prompt_tokens", 0) + last_usage_norm.get("completion_tokens", 0),
    }


# ---------------------------------------------------------------------
# Final reshape
# ---------------------------------------------------------------------

def rebrand_responses(data: dict, slug: str) -> dict:
    """Swaps the upstream model id for our public product slug without
    mutating the caller's/upstream's original dict (callers of this
    keep their own reference to the pre-rebrand object for logging)."""
    # "served_by" (the upstream host's name, added 2026-10-05 for internal
    # logging) must never reach a caller — upstream hosts are secret.
    # The same goes for upstream_error / upstream_finish_reason (added
    # 2026-10-09): they carry the failed host's name and error codes.
    internal = ("served_by", "upstream_error", "upstream_finish_reason")
    return {**{k: v for k, v in data.items() if k not in internal}, "model": slug}


def to_chat_completion(data: dict, slug: str, billed_usage: dict | None = None) -> dict:
    """Full reshape of a completed (non-stream) Responses object into a
    Chat Completions `chat.completion`. `billed_usage`, when given,
    OVERRIDES data["usage"] in the output — see billed_client_usage()'s
    docstring for why the raw upstream usage on `data` is not what a
    two-pass caller should ever see. Pass None only for a single-call
    response (e.g. a fallback-to-draft path, where the draft's own
    usage already IS the correct billed figure)."""
    text, calls = responses_output_text_and_calls(data.get("output") or [])
    has_calls = bool(calls)
    # Text the model wrote next to a tool call is kept (fixed 2026-10-06): the
    # streaming path and the Anthropic shape already carry it, and OpenAI's own
    # format allows content AND tool_calls together. Only an empty text becomes
    # null.
    message = {"role": "assistant", "content": text if (text or not has_calls) else None}
    if has_calls:
        message["tool_calls"] = calls
    usage_norm = billed_usage if billed_usage is not None else usage_from_responses(data.get("usage") or {})
    return {
        "id": data.get("id"),
        "object": "chat.completion",
        "created": data.get("created_at") or data.get("created"),
        "model": slug,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason(data, has_calls)}],
        "usage": client_usage(usage_norm) if "prompt_cache_hit_tokens" not in usage_norm else usage_norm,
    }


def reshape(data: dict, caller_shape: str, slug: str, billed_usage: dict | None = None) -> dict:
    if caller_shape == "chat_completions":
        return to_chat_completion(data, slug, billed_usage=billed_usage)
    if caller_shape == "anthropic":
        from . import anthropic_api as aa  # local import: anthropic_api imports this module, so a top-level import here would be circular
        return aa.to_anthropic_message(data, slug, billed_usage=billed_usage)
    rebranded = rebrand_responses(data, slug)
    if billed_usage is not None:
        rebranded["usage"] = {
            "input_tokens": billed_usage.get("prompt_tokens", 0),
            "output_tokens": billed_usage.get("completion_tokens", 0),
            "total_tokens": billed_usage.get("prompt_tokens", 0) + billed_usage.get("completion_tokens", 0),
            "input_tokens_details": {"cached_tokens": billed_usage.get("cached_tokens", 0)},
        }
    return rebranded


# ---------------------------------------------------------------------
# Request body construction
# ---------------------------------------------------------------------

def render_draft_for_critic(draft_text: str | None, draft_calls: list[dict]) -> str:
    """Renders whatever the draft pass produced — plain text, one or
    more tool calls, or both — into one string that gets embedded in
    the critic's review prompt (see app/critic/kael.py's
    {draft_response} placeholder). This is what makes tool-call drafts
    reviewable at all: the critic prompt already asks the critic to
    revisit "which tool to call" as one of the decisions worth
    reviewing — this function is what actually puts a tool call in
    front of the critic in a form it can read and react to, instead of
    the tool-call decision skipping review entirely. Bug fix
    (2026-08-20): before this existed, a draft that chose to call a
    tool never reached the critic at all — see app/kael_pipeline.py's
    module docstring for the full history of that bug."""
    parts = []
    if draft_text:
        parts.append(draft_text)
    for call in draft_calls:
        fn = call.get("function", {})
        parts.append(f"[tool call chosen by the draft: {fn.get('name')}(arguments={fn.get('arguments')})]")
    return "\n\n".join(parts) if parts else "(the draft produced no reviewable output)"


# Difficulty values app/router/kael.py's ROUTER_PROMPT is instructed to
# use, verbatim and case-sensitively — see that module for the full
# instruction text. Not meant to be extended with a third value (e.g.
# "MEDIUM"): the tie-breaker section of that prompt is deliberately
# written so anything that isn't confidently, unambiguously easy already
# resolves to "HARD" at the model layer, so the orchestrator only ever
# needs to special-case the one value that means "skip the critic pass."
_DIFFICULTY_EASY = "EASY"
_DIFFICULTY_HARD = "HARD"

# Anchored at the very start of the text (^), matching ROUTER_PROMPT's
# own instruction that the tag must be the first thing in the draft's
# response — case-SENSITIVE (no re.IGNORECASE): a model that emits
# "easy"/"Easy" instead of the exact instructed "EASY" has already
# failed to follow the one formatting rule this whole mechanism depends
# on, and failing the match here — falling through to the HARD default
# below — is the correct, safe consequence of that, not a bug to work
# around with a more lenient match. The closing tag is OPTIONAL
# (`(?:...)?`) specifically to still recognize and strip a
# well-formed-enough opening-tag-plus-word even if the model drops the
# closing tag — a plausible minor compliance slip that would otherwise
# leave a raw, unstripped tag fragment sitting in what the critic (or,
# on an EASY rating, the client) sees, for no real safety benefit: the
# opening tag alone, built from this request's own unpredictable
# boundary (see build_router_message()'s docstring), is already what
# makes this un-spoofable — the closing tag is a nice-to-have for
# well-formed output, not the actual security boundary.
_DIFFICULTY_TAG_TEMPLATE = r"^\s*<{tag}>\s*(EASY|HARD)\s*(?:</{tag}>)?\s*"


def extract_difficulty_and_strip(draft_data: dict, boundary: str) -> tuple[dict, str]:
    """Reads the draft pass's own difficulty rating out of its response
    text, strips the tag it was carried in out of that text, and returns
    (cleaned_draft_data, difficulty) — difficulty is always exactly
    "EASY" or "HARD", never anything else, never None (see the fail-safe
    default below).

    MUST be called on draft_data before EITHER downstream use of it:
    before responses_output_text_and_calls() extracts draft_text for the
    critic prompt (critic.build_critic_message()), and before draft_data
    is ever reshape()'d into what a caller receives. Calling this first
    and deriving everything else from its return value (rather than
    computing draft_text once, then separately trying to strip the tag
    out of that string, then remembering to ALSO patch draft_data before
    it's returned to a caller on the skip-critic path) is deliberate —
    see two_pass_pipeline.py's own "Difficulty routing" section for the
    exact call order this depends on. Getting that order wrong in either
    direction reopens exactly the two leaks this whole mechanism exists
    to close: the tag reaching the critic, or the tag reaching the
    client.

    Fail-safe default, always: if the tag is missing, malformed, or
    contains anything other than the exact word "EASY" or "HARD", this
    returns (draft_data UNCHANGED, "HARD") — never raises, never guesses,
    never treats "couldn't parse this" as license to skip the critic
    pass. A parsing failure here degrades to exactly the pipeline's
    pre-2026-09-13 default behavior (always run the critic), not to some
    new, riskier behavior — see _DIFFICULTY_TAG_TEMPLATE's own comment
    for why the match itself is deliberately strict (case-sensitive,
    anchored) while what happens on a non-match is deliberately the safe
    direction.

    Only ever inspects/modifies the FIRST "message"-type item's
    "output_text" parts in draft_data["output"] — in practice there is
    at most one such item with at most one such part for a
    Chat-Completions-derived draft (see response_api._cc_output_and_usage(),
    the only thing that ever builds this app's `output` arrays: at most
    one `{"type": "message", ...}` entry, built from one joined content
    string, before any `function_call` entries), but this walks the
    structure the same defensive way responses_output_text_and_calls()
    itself does rather than assuming output[0] is always that item."""
    tag = f"task_difficulty_{boundary}"
    pattern = re.compile(_DIFFICULTY_TAG_TEMPLATE.format(tag=re.escape(tag)))
    output = draft_data.get("output") or []
    matched = False
    difficulty = _DIFFICULTY_HARD
    new_output = []
    for item in output:
        if not matched and item.get("type") == "message":
            new_content = []
            for part in item.get("content") or []:
                if not matched and part.get("type") == "output_text" and part.get("text"):
                    m = pattern.match(part["text"])
                    if m:
                        matched = True
                        difficulty = m.group(1)
                        new_content.append({**part, "text": part["text"][m.end():]})
                        continue
                new_content.append(part)
            new_output.append({**item, "content": new_content})
        else:
            new_output.append(item)
    if not matched:
        return draft_data, _DIFFICULTY_HARD
    return {**draft_data, "output": new_output}, difficulty


# ---------------------------------------------------------------------
# Chat Completions upstream (outbound) — the only upstream body-builder
# left in this module. Used to sit alongside a build_responses_body()
# that built a POST /v1/responses body for a literal Responses-API
# upstream (DeepSeek/OpenAI) — that was Aura Beta's entire upstream and,
# before 2026-08-30, Kael Beta's too. Removed 2026-09-08 along with Aura
# Beta itself, once no PassConfig anywhere could select that path
# anymore — see the module docstring above for the fuller history, and
# build_chat_completions_body()'s own docstring below for why this one
# function can't just be extended back into a general-purpose,
# shape-agnostic body-builder even if that path returns: the two wire
# shapes don't share enough structure (no `instructions` field, a flat
# `messages` list instead of `input` + separate instructions, `max_tokens`
# instead of `max_output_tokens`, a `reasoning`/`reasoning_effort` shape
# that itself varies by provider) to build both without an internal
# if/else on nearly every field.
# ---------------------------------------------------------------------

def tools_from_responses(tools: list[dict] | None) -> list[dict] | None:
    """Inverse of tools_to_responses() above: Responses' flattened
    function-tool shape ({"type": "function", "name", "parameters",
    "description"?}) back into Chat Completions' nested shape
    ({"type": "function", "function": {"name", "description",
    "parameters"}}) — confirmed against Z.ai's own
    FunctionToolSchema/FunctionObject schemas (docs.z.ai/api-reference/
    llm/chat-completion, fetched 2026-08-30), which require `function`
    nested and, unlike tools_to_responses()'s own input side,
    additionally mark `description` as REQUIRED on FunctionObject — so
    this always sends a `description` key (defaulting to "" when the
    caller didn't give one), rather than the conditional
    `if "description" in fn` tools_to_responses() uses, specifically to
    avoid a schema-validation rejection GLM's stricter requirement would
    otherwise cause. This is the one place in the app `tools` is
    converted OUT of the internal Responses-flattened shape — every
    other use of `tools` stays in that one shape the whole way through,
    per this module's "one internal shape" design (see module
    docstring); this function is a deliberately scoped exception, not a
    second parallel convention."""
    if tools is None:
        return None
    nested = []
    for t in tools:
        if isinstance(t, dict) and t.get("type") == "function" and "function" not in t:
            nested.append({
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters"),
                },
            })
        else:
            nested.append(t)
    return nested


def build_chat_completions_body(
    *,
    provider: str,
    model: str,
    input_items: list[dict],
    tools: list[dict] | None,
    reasoning_effort: str,
    max_output_tokens: int,
    system_identity: str | None = None,
    trailing_messages: list[dict] | None = None,
    stream: bool,
    provider_routing: dict | None = None,
    session_id: str | None = None,
) -> dict:
    """Builds a Chat-Completions-shaped upstream body — the only upstream
    body-builder left in this module (see the section header above this
    function for what used to sit alongside it). Fixed, explicit set of
    NAMED fields only, deliberately: this function never does
    `body = dict(incoming_request)`. One exception to "every named field
    is unconditionally sourced from models/kael/config.py", as of the
    2026-08-31 OpenRouter switch: `reasoning_effort` may now be a
    caller-supplied value for Kael Beta specifically (see
    kael_pipeline._resolve_reasoning_tier() and the top-level README's
    "OpenAI-compatible, but not caller-tunable" section for that scoped
    exception). This function itself doesn't know or care where its
    `reasoning_effort` argument came from — it only ever reads the named
    parameter, never the raw request body — so the "no
    dict(incoming_request)" guarantee holds regardless of which layer
    above it decided the value.

    Message order (see the module docstring's "Chat Completions upstream"
    section for the full reasoning; changed 2026-10-01): system_identity
    FIRST as its own system message — then input_items, exactly as
    prepare_input_items() already produced them (caller's own
    <caller_system_prompt_{boundary}>-wrapped content, if any, in whatever
    position the caller sent it, ending with the <kael_context_{boundary}>
    system message) — then trailing_messages (the difficulty-router
    instruction on the draft pass; the critic prompt with the draft
    embedded on the critic pass). Nothing here reorders input_items
    itself; this function only puts system_identity before it and
    trailing_messages after it.

    reasoning shape — branches on `provider`, two real upstream dialects:

    - `provider == "openrouter"`: OpenRouter normalizes reasoning control
      across every provider it fronts into one unified field,
      `"reasoning": {"effort": ...}` (confirmed against
      openrouter.ai/docs/use-cases/reasoning-tokens, fetched 2026-08-31).
      Kael Beta's model, deepseek/deepseek-v4.1-flash (both passes),
      exposes a real three-tier low/high/max enum for this field
      (`reasoning.supported_efforts` is `["max","high","low"]` per
      OpenRouter's live `/api/v1/models` response), so whatever value is
      passed in here is sent through unchanged to both passes, no
      remapping needed. A
      `provider_routing` dict, when given, is sent verbatim as the
      request's top-level `"provider"` key — OpenRouter's own routing
      namespace (order/allow_fallbacks/preferred_max_latency/
      preferred_min_throughput — confirmed against
      openrouter.ai/docs/guides/routing/provider-selection). This is a
      DIFFERENT, unrelated "provider" from this function's own `provider`
      parameter above: that one picks which upstream service THIS app
      calls (glm/openrouter/...); OpenRouter's is which of ITS upstream
      hosts (e.g. Relace) it routes the request to. Both exist in the
      same outbound body under the same word, meaning two different
      things at two different layers — see
      two_pass_pipeline.PassConfig's own `provider` field for the
      app-side namespace this mirrors. `session_id` (added 2026-10-05,
      OpenRouter only) is sent as the top-level `"session_id"` field —
      OpenRouter's documented sticky-routing key, so follow-up turns of
      one conversation land on the host that already holds the prompt
      cache; see provider_routing.py's module docstring for why this is
      used instead of pinning a provider.
    - anything else (currently just `"glm"`, a direct Z.ai call): GLM's
      own native fields — a flat `reasoning_effort` string (confirmed
      against Z.ai's OpenAPI enum for glm-5.3-flash, `[max, high, low]`,
      no "medium") plus `thinking: {"type": "enabled"}` sent explicitly,
      since "enabled" is glm-5.3-flash's only supported value (the whole
      5.3 generation always reasons; `disabled` isn't accepted) —
      explicit rather than relying on a default that happens to already
      be right. No `provider_routing` concept exists on this branch; the argument
      is ignored if somehow passed alongside `provider="glm"`.

    max_output_tokens -> `max_tokens`, this wire shape's field name for
    it (not `max_output_tokens`, the Responses API's name) — capped
    upstream by whichever model is actually called; models/kael/
    config.py's values are kept under each model's real ceiling, so this
    function doesn't clamp — same "config is the source of truth, not a
    defensive clamp downstream" pattern the Responses-shape side uses."""
    messages: list[dict] = []
    if system_identity:
        messages.append({"role": "system", "content": system_identity})
    messages.extend(input_items)
    if trailing_messages:
        messages.extend(trailing_messages)
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_output_tokens,
        "stream": stream,
    }
    if provider == "openrouter":
        body["reasoning"] = {"effort": reasoning_effort}
        if provider_routing:
            body["provider"] = provider_routing
        if session_id:
            body["session_id"] = session_id
    else:
        body["reasoning_effort"] = reasoning_effort
        body["thinking"] = {"type": "enabled"}
    if tools:
        body["tools"] = tools_from_responses(tools)
    return body


# ---------------------------------------------------------------------
# Chat Completions upstream (inbound) — a chat.completion (or a
# finished stream accumulator, see the cc_accumulator_* trio below)
# normalized into the SAME Responses-shaped dict a real Responses API
# response already is, so responses_output_text_and_calls(),
# usage_from_responses(), finish_reason(), and reshape() all read it
# with zero changes and no branch of their own on which upstream shape
# actually produced it.
#
# Written against GLM/Z.ai's own documented Chat Completions response
# shape (still cited below function-by-function) since that was Kael
# Beta's upstream when this section was added. As of 2026-08-31, the
# actual bytes flowing through this code for Kael Beta are OpenRouter's
# response (for deepseek-v4.1-flash), not a direct GLM one.
#
# CONFIRMED 2026-09-13 (was an open question below until now, see git
# history for the prior text): OpenRouter does NOT pass each provider's
# native finish_reason through unchanged on the field this code reads.
# Per OpenRouter's own docs (openrouter.ai/docs/api_reference/overview,
# "Response body" section) and its "Standardized finish reasons"
# announcement (openrouter.ai/announcements/standardized-finish-reasons):
# `finish_reason` is ALWAYS normalized to one of exactly tool_calls /
# stop / length / content_filter / error, for every model and provider
# it fronts — GLM's own native strings (sensitive /
# model_context_window_exceeded / network_error, cited below) never
# appear there. The raw provider value survives separately, on a
# DIFFERENT field, `native_finish_reason`, which this code has never
# read. Net effect: _CC_FAILED_FINISH_REASONS below was checking
# `finish_reason` for values that stopped appearing in that field the
# day this app switched to OpenRouter (2026-08-31) — GLM emitting
# `sensitive` upstream now normalizes to `content_filter` (or possibly
# `error`) by the time this code sees it, so the old check has almost
# certainly been silently dead for every OpenRouter-routed call since
# that switch: a real content-safety block or context-overflow from
# either upstream model would have fallen through to `_cc_status()`'s
# `return "completed"` default instead of being caught as `"failed"` —
# treated as a normal, if short or empty, successful completion, with
# nothing in two_pass_pipeline.py's failure/fallback handling ever
# triggered. Fixed below to check OpenRouter's actual normalized
# vocabulary. `native_finish_reason` is intentionally NOT read for the
# failure check itself (checking the vendor-specific value would put
# this code right back to silently breaking the next time a provider's
# native reason list changes, or the day a second provider gets added
# behind a DIFFERENT vendor's native vocabulary) — see
# chat_completion_to_responses_shape()/accumulate_cc_chunk() below for
# where native_finish_reason IS captured and threaded through, purely
# for logging/tracing visibility into WHY a given "failed" happened, not
# for detecting THAT it happened.
# ---------------------------------------------------------------------

# OpenRouter's own normalized failure-shaped values (confirmed against
# its docs, see above) — content_filter covers every provider's own
# safety/sensitivity block (GLM's `sensitive` included), error covers
# everything else OpenRouter itself couldn't complete (GLM's
# `model_context_window_exceeded`/`network_error` included, along with
# OpenRouter's own upstream-provider failures). length is handled
# separately below, same as it always was — it's an incomplete
# completion, not a failed one.
_CC_FAILED_FINISH_REASONS = frozenset({"content_filter", "error"})


def _cc_status(finish_reason: str | None) -> str:
    """OpenRouter's normalized `finish_reason` -> the Responses-shape
    `status` vocabulary the rest of this module already reads (see
    finish_reason() above, which checks status == "incomplete", and
    _run_nonstream()'s own status == "failed" check in
    two_pass_pipeline.py). OpenRouter's normalized enum (see the section
    header above for the citations) is exactly tool_calls/stop/length/
    content_filter/error — `length` maps the same way a Responses API
    `status: "incomplete"` already does; content_filter/error map to
    "failed" so a content-level failure from either upstream model is
    handled the same way _run_nonstream() already handles a
    Responses-shape `status: "failed"` (log it, fall back to the draft)
    instead of silently being treated as a normal empty/short
    completion."""
    if finish_reason in _CC_FAILED_FINISH_REASONS:
        return "failed"
    if finish_reason == "length":
        return "incomplete"
    return "completed"


def _cc_output_and_usage(content: str, reasoning_content: str, tool_calls: list[dict], usage: dict) -> tuple[list, dict]:
    """Shared by chat_completion_to_responses_shape() (non-streamed) and
    cc_accumulator_to_responses_shape() (streamed) so the actual
    output-item and usage shaping lives in exactly one place. Not
    exposed on its own — both callers below have already reduced their
    very different inputs (a single JSON object vs. a folded-together
    stream accumulator) down to this same flat (content,
    reasoning_content, tool_calls, usage) tuple before calling this."""
    output = []
    if content:
        # Backstop against the model naming/self-identifying as its real
        # underlying vendor — see app/identity_guard.py (added
        # 2026-09-15) for the full reasoning. Applied here rather than
        # in each of this function's two callers so BOTH the
        # non-streamed path (chat_completion_to_responses_shape) and the
        # end-of-stream accumulated record (cc_accumulator_to_
        # responses_shape — used for billing/tracing and, for the draft
        # pass, what the critic actually reviews) get the same
        # guarantee from one place. This does NOT cover the live,
        # incremental relay of a streaming response — those deltas are
        # already on their way to the client before this function ever
        # runs on the fully-accumulated text; that path has its own
        # equivalent (app/two_pass_pipeline.py's StreamIdentityGuard,
        # fed chunk-by-chunk inside consume_pass()).
        content = identity_guard.scrub_identity_leaks(content)
        output.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]})
    for tc in tool_calls:
        fn = tc.get("function") or {}
        args = fn.get("arguments", "")
        if not isinstance(args, str):
            # GLM's own schema types this as `object` but every real
            # OpenAI-compatible wire response (and this app's own
            # function_call_item_to_tool_call() above) treats it as a
            # JSON-encoded STRING the caller parses — defensive re-
            # encode here in case a given deployment actually returns a
            # parsed object, so this never crashes on json.loads()
            # downstream regardless of which one GLM sends.
            args = json.dumps(args)
        output.append({
            "type": "function_call", "call_id": tc.get("id"),
            "name": fn.get("name"), "arguments": args, "status": "completed",
        })
    usage_norm = {
        "input_tokens": usage.get("prompt_tokens", 0) or 0,
        "output_tokens": usage.get("completion_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
        "input_tokens_details": {"cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0},
    }
    # reasoning_content isn't carried into `output` — same treatment
    # responses_output_text_and_calls() above already gives a Responses
    # API `reasoning` item: internal chain-of-thought, not caller-visible
    # content, never contributes to `text`.
    del reasoning_content
    return output, usage_norm


def chat_completion_to_responses_shape(cc: dict) -> dict:
    """A complete (non-streamed) GLM chat.completion JSON body ->
    Responses-shaped dict. Used by two_pass_pipeline._post_chat_
    completions() immediately after the upstream call returns, so
    _run_nonstream() (and everything it calls) never sees GLM's native
    shape at all."""
    choice = (cc.get("choices") or [{}])[0] if cc.get("choices") else {}
    message = choice.get("message") or {}
    finish = choice.get("finish_reason")
    output, usage_norm = _cc_output_and_usage(
        message.get("content") or "", reasoning_text_from_delta(message),
        message.get("tool_calls") or [], cc.get("usage") or {},
    )
    # OpenRouter reports a provider failure that interrupts generation as a
    # top-level `error` object (and finish_reason "error"). Only its code,
    # typed error_type and host name are kept (see provider_routing.safe_error_fields).
    upstream_error = provider_routing.safe_error_fields(cc.get("error") or choice.get("error"), cc.get("provider"))
    status = _cc_status(finish)
    if upstream_error is not None and status == "completed":
        status = "failed"  # an error object with no failed finish_reason is still a failure
    return {
        "id": cc.get("id"),
        "created_at": cc.get("created"),
        "status": status,
        "upstream_finish_reason": finish,
        "upstream_error": upstream_error,
        # OpenRouter's own un-normalized value (see the section header
        # above) — not used for the status decision above (see
        # _CC_FAILED_FINISH_REASONS' own comment for why), carried
        # through purely so two_pass_pipeline.py's failure logging can
        # say WHY a "failed" status happened (content filter? context
        # overflow? a network blip on OpenRouter's end?) instead of just
        # THAT it happened. None on a real Responses API response and on
        # any provider OpenRouter doesn't supply this field for — every
        # caller of this key already needs to handle "reason unknown."
        "native_finish_reason": choice.get("native_finish_reason"),
        "output": output,
        "usage": usage_norm,
        # Which upstream host OpenRouter used (logging only; never sent to callers).
        "served_by": cc.get("provider") if isinstance(cc.get("provider"), str) else None,
    }


def reasoning_text_from_delta(delta) -> str:
    """The reasoning text carried by one streamed delta (or one complete
    message), whichever field name the upstream used.

    OpenRouter's documented name for streamed reasoning is `reasoning`
    (plus a structured `reasoning_details` list); `reasoning_content` is
    the DeepSeek/Z.ai-style name some hosts also send. Which one a given
    host uses can differ, and reading only one meant a host using the
    other produced no thinking titles at all. Priority: `reasoning_content`,
    then `reasoning`, then `reasoning_details` (its `reasoning.text` and
    `reasoning.summary` entries; `reasoning.encrypted` is opaque and
    skipped). Only ONE source is used per delta, never a sum: OpenRouter
    sends the same text in both `reasoning` and `reasoning_details`, and
    adding them would double it. Returns "" when there is none."""
    if not isinstance(delta, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    details = delta.get("reasoning_details")
    if isinstance(details, list):
        parts = []
        for entry in details:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("type")
            if kind == "reasoning.text" and isinstance(entry.get("text"), str):
                parts.append(entry["text"])
            elif kind == "reasoning.summary" and isinstance(entry.get("summary"), str):
                parts.append(entry["summary"])
        return "".join(parts)
    return ""


def new_cc_accumulator() -> dict:
    """Empty running accumulator for a streamed GLM chat.completion.chunk
    sequence. Fed to accumulate_cc_chunk() once per parsed SSE `data:`
    line; finished with cc_accumulator_to_responses_shape(). Needed
    because — unlike the Responses API, where the terminal
    response.completed event carries the ENTIRE final response, usage
    included — a Chat Completions stream has no single event with the
    full message; it only exists once every delta chunk has been folded
    in, which is what this accumulator is for."""
    return {"id": None, "created": None, "content": "", "reasoning_content": "", "tool_calls": {}, "finish_reason": None, "native_finish_reason": None, "usage": None, "served_by": None, "upstream_error": None}


def accumulate_cc_chunk(acc: dict, chunk: dict) -> dict:
    """One immutable step: current accumulator + one parsed
    chat.completion.chunk -> new accumulator (the original `acc` is
    never mutated, same "pure function" contract as everything else in
    this module). tool_calls are keyed by the chunk's own `index` field
    (the wire shape's own disambiguator for interleaved/partial
    multi-tool-call streaming, standard across OpenAI-compatible chat-
    completions APIs) so a name or arguments fragment lands on the right
    in-progress call instead of every fragment concatenating onto one.

    Whether a `usage` object shows up on the final streamed chunk is
    confirmed for OpenRouter — Kael Beta's only current caller of this
    path — but NOT for GLM/Z.ai direct, if that branch is ever pointed
    at again. OpenRouter's own streaming docs
    (openrouter.ai/docs/api_reference/streaming, fetched 2026-08-31)
    state plainly that every Chat Completions stream ends with an extra
    chunk carrying the full usage object, sent just before `[DONE]` —
    unconditional, not gated behind a `stream_options.include_usage`
    opt-in the way OpenAI's own API requires (OpenRouter documents that
    field as accepted for compatibility but a no-op: usage is always
    included regardless). That same terminal chunk can also repeat the
    same finish_reason already seen on the last content-bearing chunk,
    rather than leaving `choices` empty the way OpenAI's own
    include_usage chunk does — this function handles both shapes
    identically without needing to know which one a given chunk is:
    `choice.get("finish_reason")` is a no-op re-set to the same value
    when repeated, and a genuinely empty `choices` array (`choice = {}}`
    below) just leaves `out["finish_reason"]` at whatever the prior
    chunk already set. GLM/Z.ai direct's own behavior here was never
    confirmed against their docs (their published
    ChatCompletionTextRequest schema has no `stream_options` field at
    all) — if that branch is used, this function still degrades safely
    (whatever `usage` it last saw, all-zero if it saw none, rather than
    crashing), same as it always has; worth a real streamed call before
    trusting billed_client_usage() figures on that path specifically."""
    out = {**acc, "tool_calls": dict(acc["tool_calls"])}
    out["id"] = out["id"] or chunk.get("id")
    out["created"] = out["created"] or chunk.get("created")
    # OpenRouter names the upstream host that served the request in a
    # top-level `provider` field on every chunk (added 2026-10-05, logging only).
    if isinstance(chunk.get("provider"), str):
        out["served_by"] = out.get("served_by") or chunk["provider"]
    choices = chunk.get("choices") or []
    choice = choices[0] if choices else {}
    delta = choice.get("delta") or {}
    if delta.get("content"):
        out["content"] += delta["content"]
    reasoning_piece = reasoning_text_from_delta(delta)
    if reasoning_piece:
        out["reasoning_content"] += reasoning_piece
    for tc in delta.get("tool_calls") or []:
        idx = tc.get("index", 0)
        slot = dict(out["tool_calls"].get(idx) or {"id": None, "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]
        out["tool_calls"][idx] = slot
    if choice.get("finish_reason"):
        out["finish_reason"] = choice["finish_reason"]
    if choice.get("native_finish_reason"):
        out["native_finish_reason"] = choice["native_finish_reason"]
    if chunk.get("usage"):
        out["usage"] = chunk["usage"]
    # A mid-stream failure arrives as a top-level `error` object on the last
    # chunk (alongside finish_reason "error"). Keep only its safe fields:
    # code, error_type, host (see provider_routing.safe_error_fields).
    if isinstance(chunk.get("error"), dict):
        out["upstream_error"] = provider_routing.safe_error_fields(chunk["error"], chunk.get("provider"))
    return out


def cc_accumulator_to_responses_shape(acc: dict) -> dict:
    """Finished accumulator -> the same Responses-shaped dict
    chat_completion_to_responses_shape() builds from a non-streamed
    response, so two_pass_pipeline.consume_pass() can hand its finished
    accumulator to this and get back exactly what the Responses-shape
    streaming path already returns from its own terminal event — every
    downstream consumer (usage_from_responses(),
    responses_output_text_and_calls(), finish_reason(), reshape()) reads
    the streamed-GLM and non-streamed-GLM paths identically, and neither
    differently from a real Responses API response."""
    tool_calls = [
        {"id": acc["tool_calls"][i]["id"], "function": {"name": acc["tool_calls"][i]["name"], "arguments": acc["tool_calls"][i]["arguments"]}}
        for i in sorted(acc["tool_calls"])
    ]
    output, usage_norm = _cc_output_and_usage(acc["content"], acc["reasoning_content"], tool_calls, acc["usage"] or {})
    status = _cc_status(acc["finish_reason"])
    if acc.get("upstream_error") is not None and status == "completed":
        status = "failed"  # error chunk without a failed finish_reason: the stream was cut short
    return {
        "id": acc["id"],
        "created_at": acc["created"],
        "status": status,
        "upstream_finish_reason": acc["finish_reason"],
        "upstream_error": acc.get("upstream_error"),
        "native_finish_reason": acc["native_finish_reason"],
        "output": output,
        "usage": usage_norm,
        "served_by": acc.get("served_by"),
    }
