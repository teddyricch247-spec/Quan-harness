from app.services import memory


def test_project_memory_prompt_includes_instructions_current_and_report():
    prompt = memory.build_project_memory_revision_prompt("existing fact", "turn report text")
    assert "existing fact" in prompt
    assert "turn report text" in prompt
    assert "durable memory file for one specific software project" in prompt


def test_project_memory_prompt_marks_empty_memory_explicitly():
    prompt = memory.build_project_memory_revision_prompt("", "first ever report")
    assert "(empty — nothing recorded yet)" in prompt
    assert "first ever report" in prompt


def test_project_memory_prompt_mentions_char_budget():
    prompt = memory.build_project_memory_revision_prompt("x", "y")
    assert str(memory.MEMORY_CHAR_BUDGET) in prompt


def test_user_memory_prompt_allows_returning_unchanged():
    prompt = memory.build_user_memory_revision_prompt("account fact", "report")
    assert "account fact" in prompt
    assert "unchanged" in prompt.lower()
    assert "general preferences" in prompt


def test_user_memory_prompt_distinct_from_project_memory_prompt():
    project_prompt = memory.build_project_memory_revision_prompt("x", "y")
    user_prompt = memory.build_user_memory_revision_prompt("x", "y")
    assert project_prompt != user_prompt


def test_enforce_char_budget_noop_under_limit():
    text = "short memory file"
    assert memory.enforce_char_budget(text, limit=1000) == text


def test_enforce_char_budget_noop_exactly_at_limit():
    text = "x" * 500
    assert memory.enforce_char_budget(text, limit=500) == text


def test_enforce_char_budget_truncates_and_adds_notice():
    text = "x" * 9000
    result = memory.enforce_char_budget(text, limit=8000)
    assert len(result) <= 8000
    assert "truncated" in result
    assert result.startswith("x")


def test_enforce_char_budget_prefers_paragraph_boundary():
    first_para = "a" * 100
    second_para = "b" * 4000
    text = first_para + "\n\n" + second_para
    result = memory.enforce_char_budget(text, limit=200)
    # Should cut at the paragraph break (after first_para) rather than mid-second-para,
    # since that break falls comfortably within budget // 2.
    assert "b" * 10 not in result
    assert first_para in result


def test_enforce_char_budget_falls_back_to_hard_cut_when_no_good_boundary():
    text = "a" * 5000  # no paragraph breaks at all
    result = memory.enforce_char_budget(text, limit=200)
    assert len(result) <= 200
    assert "truncated" in result


def test_memory_hard_cap_is_larger_than_soft_budget():
    # The soft budget is a target given to the model; the hard cap is a
    # defensive backstop and must leave real room above the target, not
    # clip a well-behaved response that's only slightly over the target.
    assert memory.MEMORY_HARD_CAP > memory.MEMORY_CHAR_BUDGET
