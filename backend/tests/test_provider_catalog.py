"""
Drift guards for the BYOK preset catalog. The provider list used to be hand-synced
across the DB CHECK, schemas.LlmProvider and a frontend array; these tests make the
three backend copies fail loudly if they diverge.
"""
import re
from pathlib import Path

from app.services import provider_catalog as catalog

MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _latest_provider_check_ids() -> set[str]:
    """Provider ids from the newest migration that (re)defines llm_credentials_provider_check."""
    for path in sorted(MIGRATIONS.glob("0*.sql"), reverse=True):
        text = path.read_text()
        m = re.search(r"llm_credentials_provider_check\s+check\s*\(\s*provider\s+in\s*\((.*?)\)\s*\)", text, re.S | re.I)
        if m:
            return set(re.findall(r"'([^']+)'", m.group(1)))
    raise AssertionError("no migration defines llm_credentials_provider_check")


def test_catalog_ids_match_latest_migration_check_constraint():
    assert set(catalog.PROVIDER_IDS) == _latest_provider_check_ids()


def test_catalog_ids_match_schema_literal():
    from typing import get_args

    from app.models.schemas import LlmProvider

    assert set(get_args(LlmProvider)) == set(catalog.PROVIDER_IDS)


def test_ids_are_unique_and_exactly_one_requires_base_url():
    assert len(catalog.PROVIDER_IDS) == len(set(catalog.PROVIDER_IDS))
    assert [p.id for p in catalog.PRESETS if p.requires_base_url] == ["custom"]


def test_existing_providers_keep_their_litellm_prefixes():
    # These five predate the catalog; their model strings must not change or every
    # saved credential would start calling a different litellm route.
    assert catalog.litellm_prefix("anthropic") == "anthropic"
    assert catalog.litellm_prefix("openai") == "openai"
    assert catalog.litellm_prefix("google") == "gemini"
    assert catalog.litellm_prefix("openrouter") == "openrouter"
    assert catalog.litellm_prefix("custom") == "openai"


def test_new_providers_use_litellms_own_prefixes():
    assert catalog.litellm_prefix("together") == "together_ai"
    assert catalog.litellm_prefix("fireworks") == "fireworks_ai"
    for pid in ("groq", "deepseek", "mistral", "xai", "cerebras"):
        assert catalog.litellm_prefix(pid) == pid


def test_unknown_provider_falls_back_to_openai_compatible():
    assert catalog.litellm_prefix("does-not-exist") == "openai"


def test_public_catalog_never_leaks_internal_routing_fields():
    for entry in catalog.public_catalog():
        for private in ("models_url", "key_check_url", "auth_style", "litellm_prefix"):
            assert private not in entry
        assert {"id", "name", "blurb", "key_url", "model_placeholder", "requires_base_url", "recommended"} <= set(entry)


def test_every_non_custom_preset_has_a_model_list_endpoint_over_https():
    for p in catalog.PRESETS:
        if p.requires_base_url:
            assert p.models_url is None
        else:
            assert p.models_url and p.models_url.startswith("https://"), p.id


def test_a_reasoning_column_migration_exists_for_the_credentials_table():
    # 0013 adds llm_credentials.reasoning; the router/repo write that column by name.
    text = "\n".join(p.read_text() for p in MIGRATIONS.glob("0*.sql"))
    assert "add column if not exists reasoning jsonb" in text
