from app.services.repo_naming import suggest_repo_name


def test_simple_name_lowercased():
    assert suggest_repo_name("My Cool App") == "my-cool-app"


def test_special_characters_become_hyphens():
    assert suggest_repo_name("Bob's Widget!! 2.0") == "bob-s-widget-2.0"


def test_leading_trailing_whitespace_and_hyphens_stripped():
    assert suggest_repo_name("  -weird name-  ") == "weird-name"


def test_empty_name_falls_back_to_default():
    assert suggest_repo_name("   ") == "quan-harness-project"


def test_already_valid_slug_is_unchanged():
    assert suggest_repo_name("already-a-slug") == "already-a-slug"
