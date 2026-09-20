"""§22: language detection (for run_lint's ruleset choice) and the per-language
syntax check that runs after every file-tool edit."""
import json

from app.services.guard_rules import detect_language, filter_fatal_eslint_messages, format_fatal_eslint_messages
from app.services.text_edit import check_js_ts_heuristic, check_syntax


# --- detect_language --------------------------------------------------------


def test_python_project_detected_via_requirements_txt():
    assert detect_language(["requirements.txt", "app.py", "README.md"]) == "python"


def test_python_project_detected_via_pyproject_toml():
    assert detect_language(["pyproject.toml", "src"]) == "python"


def test_js_project_requires_both_package_json_and_eslint_config():
    # package.json alone isn't enough — §22 says "package.json plus an eslint
    # config", deliberately, since plenty of non-lintable/experimental JS repos
    # have a package.json with no lint setup at all.
    assert detect_language(["package.json", "index.js"]) == "none"


def test_js_project_detected_with_eslintrc_json():
    assert detect_language(["package.json", ".eslintrc.json", "src"]) == "js_ts"


def test_js_project_detected_with_flat_eslint_config():
    assert detect_language(["package.json", "eslint.config.js"]) == "js_ts"


def test_mixed_project_detected():
    assert detect_language(["requirements.txt", "package.json", ".eslintrc.js"]) == "mixed"


def test_unrecognized_project_returns_none():
    assert detect_language(["README.md", "LICENSE"]) == "none"


# --- check_syntax (Python) --------------------------------------------------


def test_valid_python_passes():
    assert check_syntax("app.py", "def foo():\n    return 1\n") is None


def test_broken_python_reports_line_and_message():
    finding = check_syntax("app.py", "def foo(:\n    return 1\n")
    assert finding is not None
    assert "line" in finding.lower()


def test_non_checkable_extension_returns_none():
    assert check_syntax("README.md", "# not code, and `(` unbalanced on purpose") is None


# --- check_js_ts_heuristic ---------------------------------------------------


def test_valid_js_passes():
    assert check_js_ts_heuristic("function foo() {\n  return 1;\n}\n") is None


def test_unclosed_brace_is_caught():
    finding = check_js_ts_heuristic("function foo() {\n  return 1;\n")
    assert finding is not None
    assert "unclosed" in finding.lower()


def test_mismatched_bracket_is_caught():
    finding = check_js_ts_heuristic("const x = [1, 2, 3);\n")
    assert finding is not None
    assert "unbalanced" in finding.lower()


def test_brace_inside_string_literal_is_not_miscounted():
    # A '{' inside a string must not be treated as a real opening brace.
    content = 'const s = "not a { real brace";\nfunction f() {\n  return s;\n}\n'
    assert check_js_ts_heuristic(content) is None


def test_brace_inside_template_literal_is_not_miscounted():
    content = "const s = `unbalanced { here too`;\nfunction f() {\n  return s;\n}\n"
    assert check_js_ts_heuristic(content) is None


def test_brace_inside_line_comment_is_not_miscounted():
    content = "// this comment has a stray {\nfunction f() {\n  return 1;\n}\n"
    assert check_js_ts_heuristic(content) is None


def test_brace_inside_block_comment_is_not_miscounted():
    content = "/* stray { brace in here */\nfunction f() {\n  return 1;\n}\n"
    assert check_js_ts_heuristic(content) is None


def test_escaped_quote_inside_string_does_not_end_string_early():
    # If the escape isn't handled, the string would appear to end after
    # \", leaving the real closing quote to be seen as starting a new,
    # unterminated string.
    content = 'const s = "she said \\"hi\\" to me";\nfunction f() { return s; }\n'
    assert check_js_ts_heuristic(content) is None


def test_unterminated_string_is_caught():
    finding = check_js_ts_heuristic('const s = "never closed;\n')
    assert finding is not None
    assert "unterminated" in finding.lower()


def test_valid_typescript_with_generics_passes():
    content = "function identity<T>(arg: T): T {\n  return arg;\n}\n"
    assert check_js_ts_heuristic(content) is None


# --- filter_fatal_eslint_messages / format_fatal_eslint_messages (run_lint) -


def _eslint_json(*file_results):
    return json.dumps(list(file_results))


def test_fatal_rule_finding_is_kept():
    stdout = _eslint_json({
        "filePath": "src/app.js",
        "messages": [{"ruleId": "no-undef", "severity": 2, "line": 3, "column": 5, "message": "'foo' is not defined."}],
    })
    fatal = filter_fatal_eslint_messages(stdout)
    assert len(fatal) == 1
    assert fatal[0]["ruleId"] == "no-undef"


def test_style_rule_finding_is_dropped():
    # semi/quotes/etc. are exactly the "style nitpicks" §22 says this check
    # is not for — only the fixed fatal set counts.
    stdout = _eslint_json({
        "filePath": "src/app.js",
        "messages": [{"ruleId": "semi", "severity": 2, "line": 1, "column": 1, "message": "Missing semicolon."}],
    })
    assert filter_fatal_eslint_messages(stdout) == []


def test_parse_error_is_kept_even_with_no_rule_id():
    # A genuine parse failure has ruleId=null but fatal=true — the JS/TS
    # equivalent of a Python SyntaxError, always fatal regardless of rule set.
    stdout = _eslint_json({
        "filePath": "src/app.tsx",
        "messages": [{"ruleId": None, "fatal": True, "severity": 2, "line": 1, "column": 10, "message": "Unexpected token"}],
    })
    fatal = filter_fatal_eslint_messages(stdout)
    assert len(fatal) == 1
    assert fatal[0]["message"] == "Unexpected token"


def test_clean_file_produces_no_fatal_findings():
    stdout = _eslint_json({"filePath": "src/app.js", "messages": []})
    assert filter_fatal_eslint_messages(stdout) == []


def test_malformed_json_returns_empty_rather_than_raising():
    assert filter_fatal_eslint_messages("eslint: command not found") == []


def test_format_fatal_eslint_messages_includes_location_and_rule():
    fatal = [{"filePath": "src/app.js", "line": 3, "column": 5, "ruleId": "no-undef", "message": "'foo' is not defined."}]
    formatted = format_fatal_eslint_messages(fatal)
    assert formatted == "src/app.js:3:5 [no-undef] 'foo' is not defined."
