"""
§7 ("LiteLLM exposes the configured credential's context size") + §16.2's
`call_llm` + §16.3's retry policy ("three attempts, exponential backoff,
inside a single call_llm").

Messages passed to `call_llm` are already in litellm's own (OpenAI-compatible)
chat format — role/content dicts, tool calls as an assistant message's
`tool_calls`, tool results as `role="tool"` messages. That IS "the provider's
native message format via the LLM wrapper" §17 item 6 describes: litellm is
the wrapper, and this format is what it accepts regardless of which of
Anthropic/OpenAI/Google/OpenRouter/a custom endpoint the credential actually
points at. Building that message list from session_events is agent_loop.py's
job, not this module's.

ROUGH EDGE, same honesty §23's workspace_service.py docstring models for its
own Fly-specific gap: no real Anthropic/OpenAI/Google/OpenRouter credential
was available to call in the environment this was built in (no network — see
/docs/PHASE3_NOTES.md), so nothing here has executed against a live provider.
The request/response shape follows litellm's documented interface; verify
against a real credential of each provider type before trusting this in
production, the same instruction /docs/YOUR_SETUP_CHECKLIST.md already gives
for the Fly integration.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

from app.repositories import llm_credentials as llm_credentials_repo
from app.services import provider_catalog, vault

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
DEFAULT_CONTEXT_WINDOW = 128_000  # used only if litellm's own model lookup fails — see get_context_window
DEFAULT_MAX_COMPLETION_TOKENS = 8192
# When thinking is switched on, the completion cap has to cover the thinking tokens too
# (OpenRouter sizes an effort level as a share of max_tokens), so a thinking model is
# given more room — but never more than this, and never more than the model's own cap.
THINKING_MAX_COMPLETION_TOKENS = 24_576
THINKING_ANSWER_HEADROOM = 4096  # room left for the answer / tool call on top of a raw thinking budget


class NoLlmCredentialError(RuntimeError):
    pass


class LlmCallFailedError(RuntimeError):
    """Raised after MAX_RETRIES attempts all fail — agent_loop.py catches this
    specifically to set session.status = 'failed' per §16.3, distinct from
    every other exception path."""


@dataclass
class ResolvedCredential:
    id: str
    provider: str
    model: str
    api_key: str
    base_url: str | None
    extra_headers: dict
    # Stored llm_credentials.reasoning — {} means "the model's own default behaviour".
    reasoning: dict = field(default_factory=dict)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LlmResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    # The model's thinking text, when the provider returned any (and the credential didn't
    # ask for it to be hidden). Extracted here, but agent_loop.py does not store or show it
    # yet — see docs/LING_THINKING_NOTES.md for the small patch that does. Never fed back
    # to the model either way.
    reasoning: str = ""


async def resolve_credential(project: dict) -> ResolvedCredential:
    """project.llm_credential_id if set, else the user's default credential
    (§7's own fallback — a project doesn't have to pin one explicitly)."""
    user_id = project["user_id"]
    row = None
    if project.get("llm_credential_id"):
        row = await llm_credentials_repo.get_for_user(user_id, project["llm_credential_id"])
    if row is None:
        row = await llm_credentials_repo.get_default_for_user(user_id)
    if row is None:
        raise NoLlmCredentialError(
            "This project has no LLM credential selected and this account has no default one — "
            "add one under Connections → LLM Providers."
        )
    api_key = await vault.read_secret(row["api_key_ref"])
    if api_key is None:
        raise NoLlmCredentialError("The selected LLM credential's key could not be read from the vault.")
    return ResolvedCredential(
        id=row["id"],
        provider=row["provider"],
        model=row["model"],
        api_key=api_key,
        base_url=row.get("base_url"),
        extra_headers=row.get("extra_headers") or {},
        reasoning=row.get("reasoning") or {},
    )


# provider -> litellm model-string prefix now lives on each preset in
# provider_catalog.py (one declaration per provider, instead of this map plus the DB
# CHECK plus the schema Literal plus a frontend array). "custom" is still treated as
# an OpenAI-compatible HTTP surface (the common case for a self-hosted or third-party
# endpoint reached via api_base) — a real design choice, not something §7 spells
# out; see /docs/PHASE3_NOTES.md. Unknown providers fall back to "openai" as before.


def _litellm_model_string(credential: ResolvedCredential) -> str:
    return f"{provider_catalog.litellm_prefix(credential.provider)}/{credential.model}"


# ---------------------------------------------------------------------------
# Thinking controls (OpenRouter's unified `reasoning` request object)
# ---------------------------------------------------------------------------


def build_reasoning_body(credential: ResolvedCredential) -> dict | None:
    """The `reasoning` object to send, or None to send nothing (the model's own default).

    Only OpenRouter has a uniform thinking API across models, so only OpenRouter
    credentials get one; every other provider returns None regardless of what is stored.
    Effort and a token budget are mutually exclusive (the schema enforces it on the way
    in; this takes effort if a hand-edited row somehow carries both).
    """
    if credential.provider != "openrouter":
        return None
    cfg = credential.reasoning or {}
    body: dict = {}
    effort = cfg.get("effort")
    budget = cfg.get("max_tokens")
    if effort:
        body["effort"] = effort
    elif budget:
        body["max_tokens"] = int(budget)
    if cfg.get("show") is False:
        body["exclude"] = True
    return body or None


def completion_token_cap(credential: ResolvedCredential, reasoning_body: dict | None) -> int:
    """max_tokens for the call. 8192 as always, unless thinking is actually on — then the
    cap must leave room for the thinking itself or the answer (or tool call) gets starved."""
    thinking_on = bool(reasoning_body) and reasoning_body.get("effort") != "none" and (
        "effort" in reasoning_body or "max_tokens" in reasoning_body
    )
    if not thinking_on:
        return DEFAULT_MAX_COMPLETION_TOKENS
    profile = provider_catalog.reasoning_profile(credential.provider, credential.model)
    model_cap = profile.max_output_tokens if profile else None
    cap = THINKING_MAX_COMPLETION_TOKENS
    if "max_tokens" in reasoning_body:
        cap = max(cap, int(reasoning_body["max_tokens"]) + THINKING_ANSWER_HEADROOM)
    if model_cap:
        cap = min(cap, model_cap)
    return cap


_REASONING_REJECTION = re.compile(r"reason|effort|thinking", re.I)


def _looks_like_reasoning_rejection(exc: Exception) -> bool:
    """A provider refusing the thinking level we asked for (an effort it doesn't know, a
    budget it can't take) — as opposed to a network blip or a bad key. Deliberately a text
    match: litellm surfaces these as assorted BadRequest shapes per provider."""
    if getattr(exc, "status_code", None) not in (400, 422):
        return False  # includes "no status at all" (timeouts, DNS) — never a thinking-level problem
    return bool(_REASONING_REJECTION.search(str(exc)))


def _strip_reasoning_level(kwargs: dict) -> bool:
    """Drop the effort/budget from an in-flight request (keeping `exclude`), so the model
    falls back to its own default thinking. True if there was something to drop."""
    body = (kwargs.get("extra_body") or {}).get("reasoning")
    if not body or not ({"effort", "max_tokens"} & set(body)):
        return False
    remaining = {k: v for k, v in body.items() if k not in ("effort", "max_tokens")}
    if remaining:
        kwargs["extra_body"] = {**kwargs["extra_body"], "reasoning": remaining}
    else:
        kwargs["extra_body"] = {k: v for k, v in kwargs["extra_body"].items() if k != "reasoning"} or None
        if kwargs["extra_body"] is None:
            del kwargs["extra_body"]
    kwargs["max_tokens"] = DEFAULT_MAX_COMPLETION_TOKENS
    return True


def _extract_reasoning(message) -> str:
    """The model's thinking text from a litellm message, whichever field the provider path
    used: litellm's normalised `reasoning_content`, OpenRouter's raw `reasoning`, or either
    tucked into `provider_specific_fields`. Empty string if there is none."""
    candidates = [getattr(message, "reasoning_content", None), getattr(message, "reasoning", None)]
    extra = getattr(message, "provider_specific_fields", None)
    if isinstance(extra, dict):
        candidates += [extra.get("reasoning_content"), extra.get("reasoning")]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return ""



def _to_function_tools(tool_schemas: list[dict]) -> list[dict]:
    """tool_schemas.py's dicts use Anthropic-native `input_schema` naming;
    litellm's unified interface expects OpenAI-style `function.parameters`."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tool_schemas
    ]


def get_context_window(credential: ResolvedCredential) -> int:
    """Best-effort; falls back to DEFAULT_CONTEXT_WINDOW rather than raising —
    compaction.should_compact() degrades gracefully on an under-estimate (it
    just compacts a bit earlier than strictly necessary), which is a far
    better failure mode than a turn loop that can't proceed at all because a
    model-info lookup failed for an unfamiliar model string."""
    try:
        import litellm

        info = litellm.get_model_info(_litellm_model_string(credential))
        window = info.get("max_input_tokens") or info.get("max_tokens")
        return int(window) if window else DEFAULT_CONTEXT_WINDOW
    except Exception:  # noqa: BLE001 — see docstring
        return DEFAULT_CONTEXT_WINDOW


def _apply_prompt_caching(messages: list[dict], credential: ResolvedCredential) -> list[dict]:
    """§17: "the static portion of the system prompt... is identical on
    every call within a session and doesn't need to be rebuilt or resent as
    new content on every call_llm." Every call today resends the full
    system prompt as plain text with no cache marker at all, so the
    provider reprocesses (and, where billed per-input-token, rebills) the
    same ~static block on every single iteration of a turn — see
    /docs/PHASE3_NOTES.md. This marks system_prompt.assemble_static()'s
    exact text as an Anthropic prompt-caching breakpoint when it's present
    as the literal prefix of the system message.

    Scoped to the Anthropic provider only, deliberately, not attempted for
    the other four: litellm's `cache_control` content-block convention is a
    documented, stable pattern for Anthropic's own API. OpenAI already
    caches any repeated prompt prefix over ~1024 tokens automatically with
    no marker needed, so it needs nothing here. Gemini's prompt caching is a
    materially different mechanism — an explicit cache-object create/TTL
    call, not a per-request content-block flag — and what an unrecognized
    `cache_control` key does when forwarded through litellm to OpenRouter or
    a custom/openai-compatible endpoint is unverified against a real
    endpoint (this whole module was written with no network access — see
    /docs/PHASE3_NOTES.md's "never run against live infra" note). Rather
    than guess at either, both are left exactly as before.

    Fails open by design: if the system message isn't in the exact shape
    this expects (wrong role, non-string content, or content that doesn't
    start with the current static prefix — e.g. a future caller building
    its own system_text differently), messages are returned unchanged
    rather than raising. A missed cache breakpoint is a cost optimization
    lost, not a correctness bug, and this must never be why a turn fails."""
    if credential.provider != "anthropic" or not messages:
        return messages
    first = messages[0]
    if first.get("role") != "system" or not isinstance(first.get("content"), str):
        return messages

    from app.services import system_prompt

    static_text = system_prompt.assemble_static()
    if not first["content"].startswith(static_text):
        return messages

    dynamic_text = first["content"][len(static_text):]
    cached_system: list[dict] = [{"type": "text", "text": static_text, "cache_control": {"type": "ephemeral"}}]
    if dynamic_text:
        cached_system.append({"type": "text", "text": dynamic_text})
    return [{"role": "system", "content": cached_system}, *messages[1:]]


async def call_llm(
    messages: list[dict], tools: list[dict], credential: ResolvedCredential, *, tool_choice: str = "auto"
) -> LlmResponse:
    """§16.3: three attempts, exponential backoff (2s, 4s, 8s), inside this one
    call — the caller never retries a call_llm itself. Raises
    LlmCallFailedError after the third failure; the turn loop's job (not
    this module's) is to turn that into session.status = 'failed'."""
    import litellm

    model_string = _litellm_model_string(credential)
    messages = _apply_prompt_caching(messages, credential)
    reasoning_body = build_reasoning_body(credential)
    kwargs = {
        "model": model_string,
        "messages": messages,
        "api_key": credential.api_key,
        "max_tokens": completion_token_cap(credential, reasoning_body),
    }
    if reasoning_body:
        # extra_body is litellm's pass-through into the provider's request JSON, which is
        # how OpenRouter's unified `reasoning` object reaches it unchanged.
        kwargs["extra_body"] = {"reasoning": reasoning_body}
    if tools:
        kwargs["tools"] = _to_function_tools(tools)
        kwargs["tool_choice"] = tool_choice
    if credential.base_url:
        kwargs["api_base"] = credential.base_url
    if credential.extra_headers:
        kwargs["extra_headers"] = credential.extra_headers

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = await litellm.acompletion(**kwargs)
            return _normalize_response(response)
        except Exception as exc:  # noqa: BLE001 — any provider/network failure is retried identically
            last_error = exc
            # A thinking level the model refuses must not take the whole turn down: retry
            # once, immediately, with the model's own default thinking instead.
            if _looks_like_reasoning_rejection(exc) and _strip_reasoning_level(kwargs):
                logger.warning(
                    "%s/%s rejected the configured thinking level (%s); retrying with the model default",
                    credential.provider, credential.model, type(exc).__name__,
                )
                continue
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
    raise LlmCallFailedError(f"{credential.provider}/{credential.model}: {last_error}") from last_error


def _normalize_response(response) -> LlmResponse:
    choice = response.choices[0]
    message = choice.message
    tool_calls = []
    for raw in getattr(message, "tool_calls", None) or []:
        import json

        try:
            arguments = json.loads(raw.function.arguments or "{}")
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        tool_calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments=arguments))

    usage = getattr(response, "usage", None)
    return LlmResponse(
        text=message.content or "",
        tool_calls=tool_calls,
        stop_reason=choice.finish_reason,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        reasoning=_extract_reasoning(message),
    )
