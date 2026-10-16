"""Kael: the two public models (Kael Beta and Kael Pro Beta), as thin front
ends over app/two_pass_pipeline.py's shared engine.

Each model is one product, keyed by its public slug in config.PRODUCTS. A
request is handled by the entry point for its wire shape (Chat Completions,
Responses, Anthropic Messages) and a `product` argument, which picks the model.
The entry points are the same for both models; only the settings differ, and
those come from models/kael/config.py. This module builds the two (or, for the
z tiers, three-plus-one) PassConfig objects for the chosen model and hands the
request to run_pipeline(). How a two-pass request actually runs (streaming,
tool calls, billing, tracing, the hard time ceiling) is documented in
app/two_pass_pipeline.py, not here.

Upstream. Both models run on OpenRouter's Chat Completions endpoint, through
the upstream-translation layer in app/response_api.py. The model ids, routing
and prompts are in models/kael/config.py. Each pass sends its own
provider routing object (speed-first, under a hard price ceiling).

Caller-tunable reasoning_effort. The caller names a TIER. Each model accepts
only its own tiers:

    kael-beta      low (default), high, max       2 calls per request
    kael-pro-beta  z-low (default), z-high        5 calls per request

    low     draft high, critic low                       2 calls
    high    draft high, critic high                      2 calls
    max     draft max,  critic max                       2 calls
    z-low   3x draft high (concurrent) -> fusor -> critic 5 calls
    z-high  3x draft max  (concurrent) -> fusor -> critic 5 calls

A tier the model does not offer is a 400 that names the model that does (for
example, "z-low" sent to kael-beta says to use kael-pro-beta). Anything else
is a 400 too; nothing is silently run at a different tier. There is no "off"
tier: Kael always thinks. The tier table is config.py's _TIER_DEFINITIONS,
and _resolve_reasoning_tier() below is the one validator for every shape.

Per-key thinking level (2026-10-08). Agents like Cursor cannot send
reasoning_effort, so each API key can pin a tier from the dashboard
(api_keys.thinking_level, see app/api_keys.py). A pinned tier wins over the
request, and the request's own value is then not validated. "SDK" (NULL) means
the request decides, as above. A key is not tied to a model, but every tier
belongs to exactly one model, so a pin applies only when it is one of the called
model's own tiers: a key pinned to "z-low" is pinned on kael-pro-beta and behaves
as "SDK" on kael-beta, and the other way round. See _pinned_tier() below.
"""
from fastapi import HTTPException

from . import config
from . import response_api as ra
from . import anthropic_api as aa
from .two_pass_pipeline import PassConfig, run_pipeline


def _product_info(product: str) -> dict:
    """The settings for one model. An unknown product is a programming error
    (only the routes in main.py call these functions, with a key they got from
    config.PRODUCTS), not a caller error, so it raises rather than returning 400."""
    info = config.PRODUCTS.get(product)
    if info is None:
        raise ValueError(f"unknown product {product!r}")
    return info


def _other_model_offering(tier: str, info: dict) -> dict | None:
    """The other model whose reasoning_tiers include `tier`, if any."""
    for other in config.PRODUCTS.values():
        if other["key"] != info["key"] and tier in other["reasoning_tiers"]:
            return other
    return None


def _resolve_reasoning_tier(raw, info: dict) -> str:
    """Validates and normalizes a caller-supplied tier for one model.

    `raw` is whatever the request body held at the field this wire shape uses
    for it: the flat top-level "reasoning_effort" for Chat Completions and
    Anthropic Messages, or "reasoning": {"effort": ...} for Responses. Each entry
    point extracts it before calling here.

    `raw is None` means the caller named no tier: the model's
    default_reasoning_tier. Anything else must be a tier this model offers,
    case-insensitively. A tier another model offers gets a message that names
    that model. Everything else is a real 400 in this app's standard error
    shape, never a silent fallback."""
    if raw is None:
        return info["default_reasoning_tier"]
    if not isinstance(raw, str):
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "reasoning_effort must be a string.", "type": "invalid_request_error", "param": "reasoning_effort"}},
        )
    normalized = raw.strip().lower()
    names = list(info["reasoning_tiers"])
    if normalized in names:
        return normalized
    owner = _other_model_offering(normalized, info)
    if owner is not None:
        message = f"'{raw}' is a reasoning_effort of {owner['label']}. Send model '{owner['slug']}' to use it."
    else:
        quoted = [f"'{n}'" for n in names]
        listed = ", ".join(quoted[:-1]) + f", or {quoted[-1]}"
        message = f"Invalid reasoning_effort '{raw}'. {info['label']} supports {listed}."
    raise HTTPException(
        status_code=400,
        detail={"error": {"message": message, "type": "invalid_request_error", "param": "reasoning_effort"}},
    )


def _pinned_tier(requestor: dict, info: dict) -> str | None:
    """The thinking tier pinned on the caller's API key (dashboard, API Keys
    page), or None when the key is set to "SDK" (or the request comes from
    the in-app chat, whose requestor has no key).

    A pinned tier wins over whatever the request says, and the request's own
    reasoning_effort is then not even validated: the point is agents such as
    Cursor that cannot control it, and some of them send values we would
    otherwise 400 on ("medium", "minimal"). "SDK" restores the old behavior
    exactly (request decides; nothing named means the default tier).

    Every tier belongs to exactly one model, so a pin only applies on the model
    that offers it. On the other model this returns None and the request decides
    exactly as it does for an "SDK" key (its own reasoning_effort, else that
    model's default). That is deliberate: it never 400s a call because of the
    pin, and it never runs one model at a tier of the other.

    A stored value that is no longer a real tier (config.py renamed or removed
    it) is treated as "SDK" rather than failing the request."""
    level = (requestor or {}).get("thinking_level")
    return level if level in info["reasoning_tiers"] else None


def _passes(info: dict, tier: str) -> tuple[PassConfig, PassConfig | None, PassConfig, int]:
    """Builds the PassConfig objects for one resolved tier and returns
    (draft, fusor, critic, draft_count). `fusor` is None for the two-call tiers
    and a PassConfig for the z tiers, whose `draft_count` is 3 (1 everywhere else).
    Each pass gets the effort the tier table gives it."""
    spec = info["reasoning_tiers"][tier]

    def _pass(model_key: str, routing_key: str, effort: str, max_out: int) -> PassConfig:
        return PassConfig(
            provider="openrouter", base_url=config.OPENROUTER_BASE_URL, api_key=config.OPENROUTER_API_KEY,
            model=info[model_key], reasoning_effort=effort,
            max_output_tokens=max_out,
            provider_routing=info.get(routing_key),
        )

    shared_ceiling = info.get("max_output") or 128_000
    draft = _pass("draft_model", "draft_provider_routing", spec["draft"], info["draft_max_output_tokens"])
    critic = _pass("critic_model", "critic_provider_routing", spec["critic"], shared_ceiling)
    fusor = None
    if spec.get("fusor"):
        fusor = _pass("fusor_model", "fusor_provider_routing", spec["fusor"], shared_ceiling)
    return draft, fusor, critic, int(spec.get("drafts", 1))


async def proxy_kael_chat_completion(body: dict, requestor: dict, source: str = "api", on_complete=None, *, product: str):
    """Entry point for POST /<model>/v1/chat/completions, and for the generic
    POST /v1/chat/completions router (app/main.py), which resolves the caller's
    "model" to a product key first. `product` is required: the caller must say
    which model is being run, so nothing is billed to the wrong one by default.

    `source` and `on_complete` are not read from `body`. They are set by the
    CALLER of this function (app/main.py), not the API request. Every public
    route passes source="api" and on_complete=None. The in-app chat (POST
    /api/chat/sessions/{id}/messages) is the only other caller: it passes
    source="app_chat" and an on_complete that saves the reply.

    reasoning_effort: a flat top-level "reasoning_effort" string, the Chat
    Completions field name for it. See _resolve_reasoning_tier()."""
    info = _product_info(product)
    tier = _pinned_tier(requestor, info) or _resolve_reasoning_tier(body.get("reasoning_effort"), info)
    draft, fusor, critic, draft_count = _passes(info, tier)
    input_items = ra.messages_to_input(body.get("messages"))
    tools = ra.tools_to_responses(body.get("tools"))
    client_wants_usage_chunk = bool((body.get("stream_options") or {}).get("include_usage"))
    return await run_pipeline(
        product=product, slug=info["slug"], system_identity=info.get("system_identity"),
        draft=draft, critic=critic, fusor=fusor, draft_count=draft_count, reasoning_tier=tier,
        input_items=input_items, tools=tools,
        client_wants_stream=bool(body.get("stream")), caller_shape="chat_completions",
        client_wants_usage_chunk=client_wants_usage_chunk,
        requestor=requestor, source=source, on_complete=on_complete,
    )


async def proxy_kael_response(body: dict, requestor: dict, source: str = "api", on_complete=None, *, product: str):
    """Entry point for POST /<model>/v1/responses and the generic POST /v1/responses
    router. `product` is required, as for proxy_kael_chat_completion().

    `input` and `instructions` go through response_api.responses_input_to_messages():
    typed items (input_text parts, function_call / function_call_output, reasoning)
    become the chat-message shape the pipeline works in, and `instructions` becomes
    a leading system message.

    reasoning_effort: read from the nested "reasoning": {"effort": ...} object, the
    Responses API's field name for it. See _resolve_reasoning_tier()."""
    info = _product_info(product)
    tier = _pinned_tier(requestor, info)
    if tier is None:  # no pin that applies to this model: the request decides
        reasoning = body.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, dict):
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": "reasoning must be an object, e.g. {\"effort\": \"low\"}.", "type": "invalid_request_error", "param": "reasoning"}},
            )
        tier = _resolve_reasoning_tier((reasoning or {}).get("effort"), info)
    draft, fusor, critic, draft_count = _passes(info, tier)
    input_items = ra.responses_input_to_messages(body.get("input"), body.get("instructions"))
    tools = ra.tools_to_responses(body.get("tools"))
    return await run_pipeline(
        product=product, slug=info["slug"], system_identity=info.get("system_identity"),
        draft=draft, critic=critic, fusor=fusor, draft_count=draft_count, reasoning_tier=tier,
        input_items=input_items, tools=tools,
        client_wants_stream=bool(body.get("stream")), caller_shape="responses",
        requestor=requestor, source=source, on_complete=on_complete,
    )


async def proxy_kael_messages(body: dict, requestor: dict, source: str = "api", on_complete=None, *, product: str):
    """Entry point for POST /<model>/v1/messages and the generic POST /v1/messages
    router. `product` is required, as for proxy_kael_chat_completion().

    `max_tokens` is required by Anthropic's own schema but never read, same as every
    other caller-supplied ceiling on this API. `thinking` (Anthropic's extended-
    thinking toggle) is accepted for schema compatibility and never read either:
    this app's thinking behavior (see app/thinking_summarizer.py) is unconditional."""
    info = _product_info(product)
    tier = _pinned_tier(requestor, info) or _resolve_reasoning_tier(body.get("reasoning_effort"), info)
    draft, fusor, critic, draft_count = _passes(info, tier)
    input_items = aa.anthropic_to_input(body)
    tools = aa.tools_from_anthropic(body.get("tools"))
    return await run_pipeline(
        product=product, slug=info["slug"], system_identity=info.get("system_identity"),
        draft=draft, critic=critic, fusor=fusor, draft_count=draft_count, reasoning_tier=tier,
        input_items=input_items, tools=tools,
        client_wants_stream=bool(body.get("stream")), caller_shape="anthropic",
        requestor=requestor, source=source, on_complete=on_complete,
    )
