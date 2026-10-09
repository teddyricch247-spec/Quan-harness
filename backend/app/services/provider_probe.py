"""
"Verify this key and show me the models" for a BYOK credential, before (or after)
it's saved.

Why it exists: connecting a provider used to mean typing a model ID from memory and
finding out the key or the ID was wrong only when the first agent turn failed
(after litellm's three retries — see llm_client.call_llm). This does one cheap
authenticated GET against the provider's own model-list endpoint instead, which
doubles as a key check and gives the UI a real list to pick from.

Things deliberately true of this module:

- The browser never talks to a provider. The key goes browser → this backend →
  provider, and is never logged, echoed in an error message, or stored by a probe.
  Provider error *bodies* are not forwarded either (some providers echo a masked
  key fragment back in them) — only the HTTP status is used.
- A failed probe is advice, not a gate. `create_credential` does not require one,
  and every non-`invalid_key` outcome still lets the UI offer manual model entry,
  because a provider's model list can be incomplete, paginated, or absent.
- `supports_tools` is surfaced per model where the provider says so (OpenRouter's
  `supported_parameters`, Mistral's `capabilities.function_calling`, etc.), because
  this is an agent: a model that can't call tools can't use any of the harness's
  tools. `None` means "provider didn't say", not "no".
- Custom endpoints get an SSRF guard (`check_public_url`): this backend runs on a
  cloud host, and a person-supplied URL is otherwise a way to make it call its own
  internal network. Redirects are not followed, for the same reason. KNOWN LIMIT:
  the guard resolves the hostname and httpx resolves it again when it connects, so a
  DNS-rebinding host could in principle pass the first check and hit a private
  address on the second. Closing that needs IP pinning at the transport layer; not
  done here. NOTE: `create_credential` / `llm_client.call_llm` do not apply this
  guard to a saved custom `base_url` — that predates this module and is flagged in
  the PR notes rather than silently changed.

httpx is imported lazily inside `_http_get` so the parsing and URL-guard logic stays
unit-testable without the full dependency set (tests inject `http_get`).
"""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from app.services import provider_catalog as catalog

TIMEOUT_SECONDS = 10.0
MAX_MODELS = 2000

# probe statuses (strings, not an Enum — they go straight into the JSON response)
OK = "ok"
INVALID_KEY = "invalid_key"          # provider said 401/403
NO_MODEL_LIST = "no_model_list"      # reachable, but no usable list (404, empty, unparseable)
UNREACHABLE = "unreachable"          # DNS/timeout/connection/5xx/other HTTP error
BAD_REQUEST = "bad_request"          # our own input was wrong (unknown provider, bad URL)


@dataclass
class ModelInfo:
    id: str
    name: str
    context_length: int | None = None
    supports_tools: bool | None = None
    supports_reasoning: bool | None = None  # OpenRouter: "reasoning" in supported_parameters


@dataclass
class ProbeResult:
    status: str
    message: str | None = None
    models: list[ModelInfo] = field(default_factory=list)


class ProbeNetworkError(Exception):
    pass


# (status_code, parsed_json_or_None)
HttpGet = Callable[[str, dict[str, str]], Awaitable[tuple[int, Any]]]


async def _http_get(url: str, headers: dict[str, str]) -> tuple[int, Any]:
    import httpx  # lazy — see module docstring

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:  # timeouts, connect errors, TLS errors
        raise ProbeNetworkError(type(exc).__name__) from exc
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, body


# ---------------------------------------------------------------------------
# SSRF guard (custom endpoints only)
# ---------------------------------------------------------------------------


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    # is_global is False for private, loopback, link-local (incl. cloud metadata
    # 169.254.169.254), CGNAT, reserved and documentation ranges.
    return addr.is_global and not addr.is_multicast


def check_public_url(url: str, resolver: Callable[..., list] = socket.getaddrinfo) -> str | None:
    """None if `url` is an http(s) URL whose host resolves only to public addresses,
    else a human-readable reason. Blocking (DNS) — callers in async code wrap it in
    `asyncio.to_thread`."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "The base URL must start with http:// or https://."
    host = parsed.hostname
    if not host:
        return "The base URL has no host."
    if parsed.username or parsed.password:
        return "Don't put credentials in the base URL — use the API key field."
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = resolver(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return f"Couldn't resolve {host}."
    addrs = {info[4][0] for info in infos}
    if not addrs:
        return f"Couldn't resolve {host}."
    if not all(_is_public_ip(a) for a in addrs):
        return (
            f"{host} resolves to a private or local address. This backend runs in the cloud, "
            "so it can only reach publicly routable endpoints (use a tunnel or a public URL "
            "for a self-hosted model)."
        )
    return None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_OPENAI_NON_CHAT_MARKERS = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "davinci", "babbage",
    "image", "audio", "realtime", "transcribe", "search-preview",
)
_CONTEXT_KEYS = ("context_length", "context_window", "max_context_length", "inputTokenLimit", "max_input_tokens")


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _tools_flag(item: dict) -> bool | None:
    params = item.get("supported_parameters")
    if isinstance(params, list):
        return "tools" in params
    if isinstance(item.get("supports_tools"), bool):
        return item["supports_tools"]
    caps = item.get("capabilities")
    if isinstance(caps, dict) and isinstance(caps.get("function_calling"), bool):
        return caps["function_calling"]
    return None


def _reasoning_flag(item: dict) -> bool | None:
    """OpenRouter lists `reasoning` among a thinking model's supported_parameters. Only
    meaningful where the provider reports parameters at all — otherwise None (unknown)."""
    params = item.get("supported_parameters")
    if isinstance(params, list):
        return "reasoning" in params or "include_reasoning" in params
    return None


def _keep(provider_id: str, item: dict, model_id: str) -> bool:
    """Provider-specific "is this a chat model" filter. Errs toward keeping — manual
    entry exists, but a model wrongly hidden is a model the person can't find."""
    if provider_id == "google":
        methods = item.get("supportedGenerationMethods")
        return not isinstance(methods, list) or "generateContent" in methods
    if provider_id == "openrouter":
        arch = item.get("architecture")
        outs = arch.get("output_modalities") if isinstance(arch, dict) else None
        return not isinstance(outs, list) or "text" in outs
    if provider_id == "openai":
        lowered = model_id.lower()
        return not any(marker in lowered for marker in _OPENAI_NON_CHAT_MARKERS)
    if provider_id == "together":
        kind = item.get("type")
        return not isinstance(kind, str) or kind == "chat"
    if provider_id == "mistral":
        caps = item.get("capabilities")
        return not (isinstance(caps, dict) and caps.get("completion_chat") is False)
    return True


def parse_models(provider_id: str, payload: Any) -> list[ModelInfo]:
    """Normalises every provider's list shape: OpenAI-style {"data": [...]}, Google's
    {"models": [...]}, and Together's bare top-level array."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
    else:
        return []
    if not isinstance(items, list):
        return []

    out: list[ModelInfo] = []
    seen: set[str] = set()
    for raw in items:
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, dict):
            continue
        model_id = raw.get("id") or raw.get("name")
        if not isinstance(model_id, str) or not model_id:
            continue
        if provider_id == "google" and model_id.startswith("models/"):
            model_id = model_id[len("models/"):]
        if model_id in seen or not _keep(provider_id, raw, model_id):
            continue
        seen.add(model_id)
        display = raw.get("display_name") or raw.get("displayName") or raw.get("name")
        name = display if isinstance(display, str) and display and display != model_id else model_id
        ctx = next((c for k in _CONTEXT_KEYS if (c := _int_or_none(raw.get(k))) is not None), None)
        out.append(
            ModelInfo(
                id=model_id,
                name=name,
                context_length=ctx,
                supports_tools=_tools_flag(raw),
                supports_reasoning=_reasoning_flag(raw),
            )
        )

    # Tool-capable first (this is an agent harness), unknown next, known-not last.
    rank = {True: 0, None: 1, False: 2}
    out.sort(key=lambda m: (rank[m.supports_tools], m.id.lower()))
    return out[:MAX_MODELS]


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------


def _auth_headers(preset: catalog.ProviderPreset, api_key: str) -> dict[str, str]:
    if preset.auth_style == catalog.AUTH_ANTHROPIC:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    if preset.auth_style == catalog.AUTH_GOOGLE:
        return {"x-goog-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _models_url(preset: catalog.ProviderPreset, base_url: str | None) -> str | None:
    if preset.requires_base_url:
        return f"{base_url.rstrip('/')}/models" if base_url else None
    return preset.models_url


async def probe(
    provider_id: str,
    api_key: str,
    base_url: str | None = None,
    *,
    http_get: HttpGet = _http_get,
    url_check: Callable[[str], str | None] = check_public_url,
) -> ProbeResult:
    preset = catalog.get_preset(provider_id)
    if preset is None:
        return ProbeResult(BAD_REQUEST, f"Unknown provider '{provider_id}'.")
    if not api_key.strip():
        return ProbeResult(BAD_REQUEST, "Paste an API key first.")
    if preset.requires_base_url:
        if not base_url:
            return ProbeResult(BAD_REQUEST, "A base URL is required for a custom endpoint.")
        problem = await asyncio.to_thread(url_check, base_url)
        if problem:
            return ProbeResult(BAD_REQUEST, problem)

    url = _models_url(preset, base_url)
    if url is None:
        return ProbeResult(NO_MODEL_LIST, "This provider has no model list — enter the model ID manually.")
    headers = _auth_headers(preset, api_key.strip())

    try:
        # OpenRouter's /models is public, so check the key against an authenticated
        # endpoint first; for every other provider the list call itself is the check.
        if preset.key_check_url:
            code, _ = await http_get(preset.key_check_url, headers)
            if code in (401, 403):
                return ProbeResult(INVALID_KEY, f"{preset.name} rejected this key (HTTP {code}).")
            if code >= 400:
                return ProbeResult(UNREACHABLE, f"{preset.name} returned HTTP {code} while checking the key.")

        code, body = await http_get(url, headers)
    except ProbeNetworkError as exc:
        return ProbeResult(UNREACHABLE, f"Couldn't reach {preset.name} ({exc}).")

    if code in (401, 403):
        return ProbeResult(INVALID_KEY, f"{preset.name} rejected this key (HTTP {code}).")
    if code == 404:
        return ProbeResult(
            NO_MODEL_LIST,
            "The key may be fine, but this endpoint doesn't expose a model list — enter the model ID manually.",
        )
    if code >= 400:
        return ProbeResult(UNREACHABLE, f"{preset.name} returned HTTP {code}.")

    models = parse_models(provider_id, body)
    if not models:
        return ProbeResult(
            NO_MODEL_LIST,
            "Connected, but no models were listed — enter the model ID manually.",
        )
    return ProbeResult(OK, None, models)
