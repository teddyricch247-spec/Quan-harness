"""Phase Convert (C8.1) — derive_project_name is deterministic, bounded and never empty."""
import pytest

from app.services.project_naming import FALLBACK_NAME, MAX_NAME_CHARS, derive_project_name


def test_short_prompt_becomes_the_name():
    assert derive_project_name("build me a todo app with dark mode") == "Build me a todo app with dark mode"


def test_long_prompt_is_cut_on_a_word_boundary_within_the_limit():
    name = derive_project_name("Build a REST API for a bookstore that tracks inventory and orders for staff")
    assert name == "Build a REST API for a bookstore that tracks"
    assert len(name) <= MAX_NAME_CHARS


def test_only_the_first_non_empty_line_is_used():
    assert derive_project_name("\n\n  Fix the login bug\nand also the signup one") == "Fix the login bug"


def test_urls_and_markdown_noise_are_dropped():
    assert derive_project_name("# fix the bug https://example.com/issues/12 please") == "Fix the bug please"
    assert derive_project_name("> - `code` blocks") == "Code blocks"


@pytest.mark.parametrize("prompt", [None, "", "   ", "!!!", "```", "\n\n"])
def test_nothing_usable_falls_back(prompt):
    assert derive_project_name(prompt) == FALLBACK_NAME


def test_explicit_fallback_beats_the_generic_one():
    assert derive_project_name("", fallback="widget-shop") == "Widget-shop"
    assert derive_project_name(None, fallback="") == FALLBACK_NAME


def test_the_prompt_wins_over_the_fallback():
    assert derive_project_name("Add a login page", fallback="widget-shop") == "Add a login page"


def test_a_single_overlong_word_is_hard_cut():
    name = derive_project_name("Supercalifragilisticexpialidocious" * 3)
    assert len(name) == MAX_NAME_CHARS


def test_unicode_letters_survive():
    assert derive_project_name("héllo wörld, créer une app") == "Héllo wörld, créer une app"


def test_deterministic():
    prompt = "Make a habit tracker with streaks and a weekly chart"
    assert derive_project_name(prompt) == derive_project_name(prompt)
