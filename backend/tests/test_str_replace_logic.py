"""§14.2: 'Fails loudly — no fuzzy matching, no whitespace tolerance, no
partial-match fallback — if old_str doesn't appear exactly once.'"""
import pytest

from app.services.text_edit import StrReplaceMatchError, apply_str_replace


def test_unique_match_is_replaced():
    content = "def foo():\n    return 1\n"
    result = apply_str_replace(content, "return 1", "return 2")
    assert result == "def foo():\n    return 2\n"


def test_zero_matches_raises_with_count_zero():
    with pytest.raises(StrReplaceMatchError) as exc_info:
        apply_str_replace("hello world", "goodbye", "hi")
    assert exc_info.value.count == 0


def test_multiple_matches_raises_with_exact_count():
    content = "x = 1\nx = 1\nx = 1\n"
    with pytest.raises(StrReplaceMatchError) as exc_info:
        apply_str_replace(content, "x = 1", "x = 2")
    assert exc_info.value.count == 3


def test_whitespace_must_match_exactly_no_fuzzy_tolerance():
    content = "if True:\n    pass\n"
    # old_str has different indentation — must NOT match "fuzzily"
    with pytest.raises(StrReplaceMatchError) as exc_info:
        apply_str_replace(content, "if True:\n  pass\n", "if False:\n  pass\n")
    assert exc_info.value.count == 0


def test_only_the_matched_occurrence_is_replaced_not_others():
    content = "a\nb\nc\n"
    result = apply_str_replace(content, "b", "B")
    assert result == "a\nB\nc\n"


def test_replacement_can_be_multiline():
    content = "start\nmiddle\nend\n"
    result = apply_str_replace(content, "middle", "line1\nline2")
    assert result == "start\nline1\nline2\nend\n"


def test_error_message_is_human_readable():
    with pytest.raises(StrReplaceMatchError) as exc_info:
        apply_str_replace("aaa", "a", "b")
    assert "3 times" in str(exc_info.value)
    assert "expected exactly 1" in str(exc_info.value)
