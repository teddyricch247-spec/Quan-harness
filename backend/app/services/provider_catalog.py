"""
BYOK provider presets — the single source of truth for "which providers can a
person connect, and how".

Before this module existed the provider list lived in three places that had to
be kept in sync by hand (the DB CHECK constraint, `schemas.LlmProvider`, and a
`PROVIDERS` array in the frontend) and the person had to know their provider's
model-ID spelling and base URL. Now:

- the frontend fetches this catalog from `GET /connections/llm-credentials/providers`
  instead of hard-coding its own;
- `llm_client._litellm_model_string` reads `litellm_prefix` from here;
- `tests/test_provider_catalog.py` fails if this list, `schemas.LlmProvider`, or the
  latest migration's CHECK constraint drift apart.

Adding a provider = add a `ProviderPreset` below, add its id to
`schemas.LlmProvider`, and add a migration widening `llm_credentials_provider_check`
(see db/migrations/0012_llm_provider_presets.sql for the shape).

Pure stdlib on purpose (no pydantic/httpx import) so it's importable anywhere and
unit-testable without the full backend dependency set.

ROUGH EDGE: the endpoint URLs, key-prefix hints and key-page links below were
written from each provider's public docs / litellm's provider list and have NOT been
exercised against a live key of every provider from the environment this was built
in (no network, no keys). `key_prefix_hint` is deliberately only ever a soft,
dismissible warning in the UI for that reason — never a hard validation.
"""
from dataclasses import asdict, dataclass

# How a provider's "list models" endpoint is authenticated / shaped. Drives
# provider_probe.py; kept here so a preset is one self-contained declaration.
#   bearer      — Authorization: Bearer <key>           (OpenAI and everything OpenAI-compatible)
#   anthropic   — x-api-key + anthropic-version headers
#   google      — x-goog-api-key header
AUTH_BEARER = "bearer"
AUTH_ANTHROPIC = "anthropic"
AUTH_GOOGLE = "google"


@dataclass(frozen=True)
class ProviderPreset:
    id: str                       # stored in llm_credentials.provider
    name: str                     # display name
    blurb: str                    # one line, shown under the name on the picker
    litellm_prefix: str           # model string is f"{litellm_prefix}/{model}"
    key_url: str | None           # where the person creates a key
    model_placeholder: str        # shown only if the model list can't be loaded
    auth_style: str = AUTH_BEARER
    models_url: str | None = None  # None → no model-list endpoint (manual entry only)
    key_check_url: str | None = None  # extra authenticated call when /models is public (OpenRouter)
    key_prefix_hint: str | None = None  # soft hint only — see module docstring
    requires_base_url: bool = False
    recommended: bool = False

    def to_public(self) -> dict:
        """What the frontend gets. Deliberately omits the URLs and auth style: the
        browser never calls a provider directly (it would put the key in a CORS-
        blocked cross-origin request and in the page's memory twice) — it goes
        through the backend probe."""
        d = asdict(self)
        for private in ("models_url", "key_check_url", "auth_style", "litellm_prefix"):
            d.pop(private)
        return d


# ---------------------------------------------------------------------------
# Thinking ("reasoning") controls — native levels per model
# ---------------------------------------------------------------------------
#
# OpenRouter exposes ONE unified `reasoning` request object for every model that
# thinks: {"effort": <level>} | {"max_tokens": <budget>} plus {"exclude": bool}
# (hide the thinking from the response). What differs per model is which levels
# the model natively understands, and whether thinking can be switched off. A
# `ReasoningProfile` records that, so the UI offers a model's *own* levels instead
# of a generic low/medium/high that the model might not honour.
#
# Only OpenRouter models are covered today: it is the one provider here whose
# thinking controls are uniform across models. A credential for any other provider
# simply has no reasoning config (the router rejects one rather than silently
# ignoring it).

EFFORT_NONE = "none"  # OpenRouter's "disable reasoning entirely"
# Every effort value OpenRouter's unified `reasoning.effort` accepts, weakest first.
ALL_EFFORTS: tuple[str, ...] = (EFFORT_NONE, "minimal", "low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class ReasoningProfile:
    levels: tuple[str, ...]          # native effort levels, weakest first, EXCLUDING "none"
    can_disable: bool = True         # whether effort "none" (thinking off) is meaningful
    supports_budget: bool = True     # whether a raw `max_tokens` thinking budget is accepted
    max_output_tokens: int | None = None  # the model's completion cap, thinking tokens included

    def accepted_efforts(self) -> tuple[str, ...]:
        return ((EFFORT_NONE,) if self.can_disable else ()) + self.levels

    def to_public(self) -> dict:
        return {
            "efforts": list(self.accepted_efforts()),
            "supports_budget": self.supports_budget,
        }


# Any OpenRouter model that advertises `reasoning` in `supported_parameters` but that we
# have no specific knowledge of. Deliberately conservative: the three levels every
# effort-style provider accepts, no "off" (many always-thinking models reject it).
GENERIC_REASONING = ReasoningProfile(levels=("low", "medium", "high"), can_disable=False, supports_budget=True)

# Model-specific profiles, keyed by (provider id, exact model id).
MODEL_REASONING: dict[tuple[str, str], ReasoningProfile] = {
    # inclusionAI Ling 3.1 Flash: hybrid reasoning MoE (560B total / 25B active). It thinks
    # or answers instantly, so "off" is a real mode, and it takes an effort level.
    ("openrouter", "inclusionai/ling-3.1-flash"): ReasoningProfile(
        levels=("low", "medium", "high", "xhigh"), can_disable=True, supports_budget=True,
        max_output_tokens=32_768,  # OpenRouter's listing: "reasoning tokens count toward this limit"
    ),
}


def reasoning_profile(provider_id: str, model_id: str) -> ReasoningProfile | None:
    """The profile for a (provider, model) pair; None when the provider has no thinking
    controls at all. An unknown OpenRouter model gets GENERIC_REASONING — whether the
    model thinks is something the probe reports (`supports_reasoning`), not something
    this function can know."""
    if provider_id != "openrouter":
        return None
    return MODEL_REASONING.get((provider_id, model_id), GENERIC_REASONING)


@dataclass(frozen=True)
class QuickModel:
    """A one-tap connection: the person pastes only a key, everything else is preset."""

    id: str
    provider: str          # a ProviderPreset id
    model: str             # exact model id for that provider
    name: str
    blurb: str
    free: bool = False
    note: str | None = None

    def to_public(self) -> dict:
        d = asdict(self)
        profile = reasoning_profile(self.provider, self.model)
        d["reasoning"] = profile.to_public() if profile else None
        return d


QUICK_MODELS: tuple[QuickModel, ...] = (
    QuickModel(
        id="ling-3.1-flash",
        provider="openrouter",
        model="inclusionai/ling-3.1-flash",
        name="Ling 3.1 Flash",
        blurb="Free on OpenRouter. 560B hybrid-reasoning MoE, 262k context, tool calling.",
        free=True,
        # OpenRouter's own listing says free-of-charge until Oct 13, 2026 (9:00 AM PT) per the
        # launch announcement; the price is read from OpenRouter, so it is a note not logic.
        note="Free-tier pricing was announced as running until Oct 13, 2026 — check OpenRouter's model page after that.",
    ),
)


PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        id="openrouter",
        name="OpenRouter",
        blurb="One key, hundreds of models from every major lab.",
        litellm_prefix="openrouter",
        key_url="https://openrouter.ai/keys",
        model_placeholder="anthropic/claude-sonnet-4.5",
        models_url="https://openrouter.ai/api/v1/models",
        # /models is public on OpenRouter, so listing alone proves nothing about the key.
        key_check_url="https://openrouter.ai/api/v1/key",
        key_prefix_hint="sk-or-",
        recommended=True,
    ),
    ProviderPreset(
        id="anthropic",
        name="Anthropic",
        blurb="Claude models, direct.",
        litellm_prefix="anthropic",
        key_url="https://console.anthropic.com/settings/keys",
        model_placeholder="claude-sonnet-4-6",
        auth_style=AUTH_ANTHROPIC,
        models_url="https://api.anthropic.com/v1/models?limit=1000",
        key_prefix_hint="sk-ant-",
    ),
    ProviderPreset(
        id="openai",
        name="OpenAI",
        blurb="GPT models, direct.",
        litellm_prefix="openai",
        key_url="https://platform.openai.com/api-keys",
        model_placeholder="gpt-5",
        models_url="https://api.openai.com/v1/models",
    ),
    ProviderPreset(
        id="google",
        name="Google Gemini",
        blurb="Gemini models via Google AI Studio.",
        litellm_prefix="gemini",
        key_url="https://aistudio.google.com/apikey",
        model_placeholder="gemini-2.5-pro",
        auth_style=AUTH_GOOGLE,
        models_url="https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
        key_prefix_hint="AIza",
    ),
    ProviderPreset(
        id="groq",
        name="Groq",
        blurb="Very fast open-weight models.",
        litellm_prefix="groq",
        key_url="https://console.groq.com/keys",
        model_placeholder="llama-3.3-70b-versatile",
        models_url="https://api.groq.com/openai/v1/models",
        key_prefix_hint="gsk_",
    ),
    ProviderPreset(
        id="together",
        name="Together AI",
        blurb="Open-weight models, pay per token.",
        litellm_prefix="together_ai",
        key_url="https://api.together.ai/settings/api-keys",
        model_placeholder="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        models_url="https://api.together.xyz/v1/models",
    ),
    ProviderPreset(
        id="fireworks",
        name="Fireworks AI",
        blurb="Fast open-weight model hosting.",
        litellm_prefix="fireworks_ai",
        key_url="https://fireworks.ai/account/api-keys",
        model_placeholder="accounts/fireworks/models/llama-v3p3-70b-instruct",
        models_url="https://api.fireworks.ai/inference/v1/models",
        key_prefix_hint="fw_",
    ),
    ProviderPreset(
        id="deepseek",
        name="DeepSeek",
        blurb="DeepSeek models, direct.",
        litellm_prefix="deepseek",
        key_url="https://platform.deepseek.com/api_keys",
        model_placeholder="deepseek-chat",
        models_url="https://api.deepseek.com/models",
    ),
    ProviderPreset(
        id="mistral",
        name="Mistral",
        blurb="Mistral models, direct.",
        litellm_prefix="mistral",
        key_url="https://console.mistral.ai/api-keys",
        model_placeholder="mistral-large-latest",
        models_url="https://api.mistral.ai/v1/models",
    ),
    ProviderPreset(
        id="xai",
        name="xAI",
        blurb="Grok models, direct.",
        litellm_prefix="xai",
        key_url="https://console.x.ai",
        model_placeholder="grok-4",
        models_url="https://api.x.ai/v1/models",
        key_prefix_hint="xai-",
    ),
    ProviderPreset(
        id="cerebras",
        name="Cerebras",
        blurb="Very fast open-weight inference.",
        litellm_prefix="cerebras",
        key_url="https://cloud.cerebras.ai",
        model_placeholder="gpt-oss-120b",
        models_url="https://api.cerebras.ai/v1/models",
        key_prefix_hint="csk-",
    ),
    ProviderPreset(
        id="custom",
        name="Custom endpoint",
        blurb="Any OpenAI-compatible URL (vLLM, LM Studio behind a tunnel, a gateway…).",
        litellm_prefix="openai",
        key_url=None,
        model_placeholder="my-model",
        requires_base_url=True,
    ),
)

_BY_ID = {p.id: p for p in PRESETS}

PROVIDER_IDS: tuple[str, ...] = tuple(p.id for p in PRESETS)


def get_preset(provider_id: str) -> ProviderPreset | None:
    return _BY_ID.get(provider_id)


def litellm_prefix(provider_id: str) -> str:
    """Unknown providers fall back to the OpenAI-compatible surface, same as the old
    hard-coded map's `.get(provider, "openai")`."""
    preset = _BY_ID.get(provider_id)
    return preset.litellm_prefix if preset else "openai"


def public_catalog() -> list[dict]:
    out = []
    for p in PRESETS:
        entry = p.to_public()
        # The thinking levels a model of this provider offers when we know nothing more specific
        # about it (None = the provider has no thinking controls). A model with its own profile
        # is described by /quick-models and by each saved credential's `reasoning_options`.
        profile = reasoning_profile(p.id, "")
        entry["reasoning"] = profile.to_public() if profile else None
        out.append(entry)
    return out


def public_quick_models() -> list[dict]:
    return [q.to_public() for q in QUICK_MODELS]


def get_quick_model(quick_id: str) -> QuickModel | None:
    return next((q for q in QUICK_MODELS if q.id == quick_id), None)
