"""§23.9 points 2 and 4. Only the pure parts — build_diagnosis_prompt and
parse_diagnosis_response — get direct unit tests here; `diagnose` itself is
a thin async wrapper around llm_client.call_llm with no branching logic of
its own (same reasoning memory_extraction.py's own equivalent call has no
dedicated test file for), and deploy_pipeline.py's own tests exercise it
end-to-end with call_llm mocked (see test_deploy_pipeline.py)."""
from app.services.deploy_diagnosis import DiagnosisLlmError, build_diagnosis_prompt, parse_diagnosis_response


def test_build_class_response_parses_with_fix_prompt():
    result = parse_diagnosis_response(
        '{"diagnosis": "Missing import foo", "failure_class": "build", '
        '"suggested_fix_prompt": "Add the missing import for foo"}'
    )
    assert result.failure_class == "build"
    assert result.diagnosis_text == "Missing import foo"
    assert result.suggested_fix_prompt == "Add the missing import for foo"


def test_environment_class_response_never_carries_a_fix_prompt_even_if_model_supplied_one():
    # §23.9 point 4: "Never use 'fix' framing" for an environment issue —
    # enforced regardless of what the model itself returned.
    result = parse_diagnosis_response(
        '{"diagnosis": "The database is unreachable", "failure_class": "environment", '
        '"suggested_fix_prompt": "Fix the database connection string"}'
    )
    assert result.failure_class == "environment"
    assert result.suggested_fix_prompt is None


def test_build_class_response_without_a_suggested_fix_stays_none():
    result = parse_diagnosis_response('{"diagnosis": "Something broke", "failure_class": "build"}')
    assert result.suggested_fix_prompt is None


def test_blank_suggested_fix_prompt_normalized_to_none():
    result = parse_diagnosis_response('{"diagnosis": "x", "failure_class": "build", "suggested_fix_prompt": "   "}')
    assert result.suggested_fix_prompt is None


def test_strips_markdown_fence():
    result = parse_diagnosis_response('```json\n{"diagnosis": "x", "failure_class": "build"}\n```')
    assert result.diagnosis_text == "x"


def test_rejects_non_json():
    try:
        parse_diagnosis_response("not json at all")
        assert False, "expected DiagnosisLlmError"
    except DiagnosisLlmError:
        pass


def test_rejects_invalid_failure_class():
    try:
        parse_diagnosis_response('{"diagnosis": "x", "failure_class": "oops"}')
        assert False
    except DiagnosisLlmError:
        pass


def test_rejects_missing_diagnosis():
    try:
        parse_diagnosis_response('{"failure_class": "build"}')
        assert False
    except DiagnosisLlmError:
        pass


def test_rejects_blank_diagnosis():
    try:
        parse_diagnosis_response('{"diagnosis": "   ", "failure_class": "build"}')
        assert False
    except DiagnosisLlmError:
        pass


def test_rejects_non_string_suggested_fix_prompt():
    try:
        parse_diagnosis_response('{"diagnosis": "x", "failure_class": "build", "suggested_fix_prompt": 5}')
        assert False
    except DiagnosisLlmError:
        pass


def test_prompt_names_the_failed_command_for_the_given_phase():
    prompt = build_diagnosis_prompt("build", "npm run build", "npm start", "out", "err", 1)
    assert "npm run build" in prompt
    assert "Failed phase: build" in prompt
    assert "npm start" not in prompt  # the run_cmd, irrelevant to a build-phase failure, shouldn't appear


def test_prompt_uses_run_cmd_for_start_phase_failures():
    prompt = build_diagnosis_prompt("start", "npm run build", "npm start", "out", "err", 137)
    assert "npm start" in prompt
    assert "Failed phase: start" in prompt


def test_prompt_includes_stdout_and_stderr():
    prompt = build_diagnosis_prompt("build", "x", None, "hello from stdout", "boom from stderr", 1)
    assert "hello from stdout" in prompt
    assert "boom from stderr" in prompt


# ---------------------------------------------------------------------------
# Phase 5.4 — environment_kind, which §23.8 limitation an environment failure looks like
# ---------------------------------------------------------------------------


def test_environment_failures_carry_a_recognised_kind():
    for kind in ("secrets", "cors", "oauth", "database", "other"):
        d = parse_diagnosis_response(
            f'{{"diagnosis": "x", "failure_class": "environment", "environment_kind": "{kind}", "suggested_fix_prompt": null}}'
        )
        assert d.environment_kind == kind


def test_an_unrecognised_or_missing_kind_on_an_environment_failure_becomes_other_not_an_error():
    # The extra field is lenient on purpose: a model that classified the failure correctly but
    # fumbled this field must not lose the whole diagnosis.
    for payload in ('"environment_kind": "weird"', '"environment_kind": null', '"unrelated": 1'):
        d = parse_diagnosis_response(f'{{"diagnosis": "x", "failure_class": "environment", {payload}}}')
        assert d.environment_kind == "other"


def test_a_build_failure_never_has_a_kind_even_if_the_model_supplied_one():
    d = parse_diagnosis_response('{"diagnosis": "x", "failure_class": "build", "environment_kind": "cors", "suggested_fix_prompt": "fix"}')
    assert d.environment_kind is None and d.suggested_fix_prompt == "fix"


def test_the_prompt_lists_every_kind_the_parser_accepts():
    from app.services import deploy_diagnosis as dd

    prompt = dd.build_diagnosis_prompt("start", None, "node x", "", "", 1)
    assert all(f'"{k}"' in prompt for k in dd._ENVIRONMENT_KINDS)
