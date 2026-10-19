"""A plain index.html site is detected by rule (no model call), and the agent's prompt carries the preview's limits."""
from app.services import system_prompt as sp
from app.services.deploy_detection import detect_stack_from_rules


def test_plain_index_html_is_served_as_static_files():
    result = detect_stack_from_rules({"top_level_files": ["index.html", "style.css", "app.js"]})
    assert result is not None
    assert result.run_cmd == "python3 -m http.server $PORT"
    assert result.build_cmd is None
    assert result.port == 8000
    assert result.stack == "python"  # deploy_runs_stack_check only allows the existing stack values


def test_index_html_next_to_a_package_json_is_not_treated_as_static():
    # A Vite/React project has an index.html at its root too; serving that raw would be wrong.
    scan = {"top_level_files": ["index.html", "package.json"], "package_json": '{"scripts": {"dev": "vite"}}'}
    assert detect_stack_from_rules(scan) is None


def test_index_html_next_to_python_project_files_is_not_treated_as_static():
    for key, value in (("requirements_txt", True), ("procfile", "web: x"), ("manage_py", True), ("app_py", "x = 1"), ("main_py", "x = 1")):
        scan = {"top_level_files": ["index.html"], key: value}
        assert detect_stack_from_rules(scan) is None, key


def test_html_without_an_index_page_is_left_to_the_fallback():
    assert detect_stack_from_rules({"top_level_files": ["about.html"]}) is None


def test_existing_stacks_still_win_over_the_static_rule():
    scan = {"top_level_files": ["index.html"], "package_json": '{"dependencies": {"next": "14.0.0"}}'}
    assert detect_stack_from_rules(scan).stack == "nextjs"


def test_preview_rules_block_is_in_the_prompt_and_follows_its_conventions():
    assert "PREVIEW_RULES" in sp.STATIC_BLOCK_ORDER
    block = sp.STATIC_PREVIEW_RULES
    assert block.startswith("<PREVIEW_RULES>") and block.rstrip().endswith("</PREVIEW_RULES>")
    for needle in ("index.html", "one app", "Deploy"):
        assert needle in block
    assert "\u2014" not in block  # the prompt's own no-em-dash rule
    assert "headless browser" not in sp.assemble_static()
