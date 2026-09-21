from datetime import datetime, timezone

from app.services import system_prompt as sp


def _minimal_dynamic(**overrides) -> sp.DynamicSections:
    base = dict(repo_context="app/main.py", current_datetime="2026-01-01 00:00:00 UTC (Thursday)")
    base.update(overrides)
    return sp.DynamicSections(**base)


def test_every_static_block_name_has_a_constant():
    for name in sp.STATIC_BLOCK_ORDER:
        assert hasattr(sp, f"STATIC_{name}")


def test_patch_edit_one_landed_the_mcp_sentence():
    assert "not a special" in sp.STATIC_PLATFORM_CAPABILITIES
    assert "Model Context Protocol" in sp.STATIC_PLATFORM_CAPABILITIES


def test_patch_edit_two_landed_communication_style_in_the_right_slot():
    assert "COMMUNICATION_STYLE" in sp.STATIC_BLOCK_ORDER
    idx_autonomy = sp.STATIC_BLOCK_ORDER.index("AUTONOMY_AND_CAPABILITY_BOUNDARY")
    idx_comms = sp.STATIC_BLOCK_ORDER.index("COMMUNICATION_STYLE")
    idx_security = sp.STATIC_BLOCK_ORDER.index("SECURITY")
    assert idx_autonomy < idx_comms < idx_security


def test_assemble_contains_every_static_block_in_order():
    text = sp.assemble(_minimal_dynamic())
    positions = [text.index(f"<{name}>") for name in sp.STATIC_BLOCK_ORDER]
    assert positions == sorted(positions)


def test_repo_context_and_current_datetime_always_present():
    text = sp.assemble(_minimal_dynamic())
    assert "<REPO_CONTEXT>" in text
    assert "<CURRENT_DATETIME>" in text


def test_optional_sections_omitted_when_none():
    text = sp.assemble(_minimal_dynamic())
    for name in (
        "PROJECT_KNOWLEDGE",
        "PROJECT_SECRETS",
        "WHAT_YOU_KNOW_ABOUT_THIS_PERSON",
        "WHAT_YOU_KNOW_ABOUT_THIS_PROJECT",
        "CURRENT_PLAN",
    ):
        assert f"<{name}>" not in text


def test_optional_sections_included_when_present():
    text = sp.assemble(_minimal_dynamic(current_plan="[ ] step one", project_secrets="- STRIPE_KEY"))
    assert "<CURRENT_PLAN>" in text and "step one" in text
    assert "<PROJECT_SECRETS>" in text and "STRIPE_KEY" in text


def test_dynamic_sections_come_after_every_static_block():
    text = sp.assemble(_minimal_dynamic(current_plan="[ ] a"))
    last_static_end = text.index(f"</{sp.STATIC_BLOCK_ORDER[-1]}>")
    assert text.index("<REPO_CONTEXT>") > last_static_end


def test_format_current_datetime_is_utc_and_readable():
    text = sp.format_current_datetime(datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc))
    assert text == "2026-03-04 05:06:07 UTC (Wednesday)"


def test_format_project_secrets_none_when_empty():
    assert sp.format_project_secrets([]) is None


def test_format_project_secrets_lists_names_only():
    text = sp.format_project_secrets(["STRIPE_KEY", "SENTRY_DSN"])
    assert "STRIPE_KEY" in text and "SENTRY_DSN" in text
    assert "never shown to you" in text


def test_format_current_plan_none_when_empty():
    assert sp.format_current_plan([]) is None


def test_format_current_plan_renders_status_marks():
    steps = [
        {"step": "write tests", "status": "done"},
        {"step": "wire router", "status": "in_progress"},
        {"step": "update docs", "status": "pending"},
    ]
    text = sp.format_current_plan(steps)
    assert "[x] write tests" in text
    assert "[~] wire router" in text
    assert "[ ] update docs" in text


# --- Phase 4.1/4.2: format_project_knowledge, format_what_you_know_about_* ---


def test_format_project_knowledge_none_when_empty():
    assert sp.format_project_knowledge([]) is None


def test_format_project_knowledge_renders_name_and_body():
    notes = [{"name": "Auth wrapper", "body": "see auth/README"}, {"name": "Migrations", "body": "NNN_x.sql"}]
    text = sp.format_project_knowledge(notes)
    assert "### Auth wrapper" in text
    assert "see auth/README" in text
    assert "### Migrations" in text
    assert "NNN_x.sql" in text


def test_format_what_you_know_about_this_project_none_when_empty():
    assert sp.format_what_you_know_about_this_project("") is None
    assert sp.format_what_you_know_about_this_project(None) is None
    assert sp.format_what_you_know_about_this_project("   ") is None


def test_format_what_you_know_about_this_project_returns_stripped_text():
    assert sp.format_what_you_know_about_this_project("  uses FastAPI + Next.js  ") == "uses FastAPI + Next.js"


def test_format_what_you_know_about_this_person_none_when_empty():
    assert sp.format_what_you_know_about_this_person("") is None
    assert sp.format_what_you_know_about_this_person(None) is None


def test_format_what_you_know_about_this_person_returns_stripped_text():
    assert sp.format_what_you_know_about_this_person("  prefers concise reports  ") == "prefers concise reports"


def test_assemble_includes_memory_and_knowledge_sections_when_present():
    text = sp.assemble(
        _minimal_dynamic(
            project_knowledge=sp.format_project_knowledge([{"name": "A", "body": "B"}]),
            what_you_know_about_this_person=sp.format_what_you_know_about_this_person("likes short reports"),
            what_you_know_about_this_project=sp.format_what_you_know_about_this_project("uses pytest"),
        )
    )
    assert "<PROJECT_KNOWLEDGE>" in text and "### A" in text
    assert "<WHAT_YOU_KNOW_ABOUT_THIS_PERSON>" in text and "likes short reports" in text
    assert "<WHAT_YOU_KNOW_ABOUT_THIS_PROJECT>" in text and "uses pytest" in text


def test_dynamic_section_order_matches_18s_own_list():
    text = sp.assemble(
        _minimal_dynamic(
            project_knowledge=sp.format_project_knowledge([{"name": "A", "body": "B"}]),
            project_secrets=sp.format_project_secrets(["STRIPE_KEY"]),
            what_you_know_about_this_person=sp.format_what_you_know_about_this_person("p"),
            what_you_know_about_this_project=sp.format_what_you_know_about_this_project("q"),
            current_plan="[ ] step",
        )
    )
    order = [
        "<REPO_CONTEXT>",
        "<PROJECT_KNOWLEDGE>",
        "<PROJECT_SECRETS>",
        "<WHAT_YOU_KNOW_ABOUT_THIS_PERSON>",
        "<WHAT_YOU_KNOW_ABOUT_THIS_PROJECT>",
        "<CURRENT_PLAN>",
        "<CURRENT_DATETIME>",
    ]
    positions = [text.index(tag) for tag in order]
    assert positions == sorted(positions)
