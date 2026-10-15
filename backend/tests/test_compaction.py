from app.services.compaction import (
    COMPACTION_INSTRUCTION,
    plan_compaction,
    should_compact,
    wrap_checkpoint,
)


def test_below_threshold_does_not_compact():
    assert should_compact(token_count=50_000, context_window=200_000) is False


def test_at_exactly_seventy_percent_compacts():
    assert should_compact(token_count=140_000, context_window=200_000) is True


def test_above_threshold_compacts():
    assert should_compact(token_count=190_000, context_window=200_000) is True


def test_zero_context_window_never_compacts():
    # defensive — a provider lookup that failed to resolve a context size
    # shouldn't cause every single call to think it's over budget
    assert should_compact(token_count=1000, context_window=0) is False


def test_custom_threshold_respected():
    assert should_compact(token_count=60, context_window=100, threshold=0.5) is True
    assert should_compact(token_count=40, context_window=100, threshold=0.5) is False


def test_wrap_checkpoint_contains_the_checkpoint_text_and_the_tag():
    wrapped = wrap_checkpoint("## Primary Request and Intent\n- Fix the bug")
    assert "<compacted-summary>" in wrapped
    assert "</compacted-summary>" in wrapped
    assert "Fix the bug" in wrapped
    assert "without acknowledging" in wrapped


def test_wrap_checkpoint_strips_surrounding_whitespace():
    wrapped = wrap_checkpoint("  \n  some text  \n\n")
    assert wrapped.count("some text") == 1
    assert "<compacted-summary>\nsome text\n</compacted-summary>" in wrapped


def test_instruction_keeps_every_required_section_header():
    for header in (
        "## Primary Request and Intent",
        "## Key Technical Concepts",
        "## Files and Code",
        "## Errors and Fixes",
        "## Pending Jobs",
        "## Current Work",
        "## Task List",
        "## Next Step",
        "## Critical Context",
    ):
        assert header in COMPACTION_INSTRUCTION


def test_plan_compaction_sums_only_the_dropped_prefix():
    texts = ["a" * 400, "b" * 400, "c" * 400, "d" * 400]  # ~100 tokens each
    plan = plan_compaction(texts, kept_from_index=2)
    assert plan.kept_from_index == 2
    assert plan.estimated_tokens_freed == 200  # first two messages only


def test_plan_compaction_keeping_everything_frees_nothing():
    texts = ["a" * 400, "b" * 400]
    plan = plan_compaction(texts, kept_from_index=0)
    assert plan.estimated_tokens_freed == 0
