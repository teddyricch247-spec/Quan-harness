"""§23.5 (stack detection) + §23.6 (monorepo root detection) — see
deploy_detection.py's own module docstring for why both live in one pure,
dependency-free module and therefore one test file, same convention as
test_checkpoint_fifo.py/test_scheduler_rules.py/test_tool_partition.py."""
from app.services.deploy_detection import (
    DeployTargetProposal,
    DetectionLlmError,
    detect_stack_from_rules,
    parse_root_proposal_response,
    parse_stack_detection_response,
    propose_roots_from_markers,
)

# ---------------------------------------------------------------------------
# §23.5 — rule-based stack detection
# ---------------------------------------------------------------------------


def test_dockerfile_short_circuits_before_any_other_rule():
    scan = {"dockerfile": True, "package_json": '{"dependencies": {"next": "1.0.0"}}'}
    result = detect_stack_from_rules(scan)
    assert result.stack == "dockerfile"
    assert result.build_cmd is None and result.run_cmd is None and result.port is None


def test_next_dependency_detected_with_default_port_and_dollar_port_run_cmd():
    scan = {"package_json": '{"dependencies": {"next": "14.0.0", "react": "18.0.0"}, "scripts": {"build": "next build"}}'}
    result = detect_stack_from_rules(scan)
    assert result.stack == "nextjs"
    assert result.port == 3000
    assert "$PORT" in result.run_cmd
    assert "npm install" in result.build_cmd and "npm run build" in result.build_cmd


def test_next_with_pnpm_lock_uses_pnpm_throughout():
    scan = {"package_json": '{"dependencies": {"next": "14.0.0"}}', "pnpm_lock": True}
    result = detect_stack_from_rules(scan)
    assert "pnpm install" in result.build_cmd
    assert result.run_cmd == "pnpm exec next start -p $PORT"
    assert "npx" not in result.run_cmd  # npx is the npm-branch-specific run_cmd token


def test_next_with_yarn_lock_uses_yarn_throughout():
    scan = {"package_json": '{"dependencies": {"next": "14.0.0"}}', "yarn_lock": True}
    result = detect_stack_from_rules(scan)
    assert "yarn install" in result.build_cmd
    assert result.run_cmd == "yarn next start -p $PORT"


def test_generic_node_with_start_script_detected():
    scan = {"package_json": '{"dependencies": {"express": "4.0.0"}, "scripts": {"start": "node server.js"}}'}
    result = detect_stack_from_rules(scan)
    assert result.stack == "node"
    assert result.run_cmd == "npm start"
    assert result.port is None  # §23.5's own "all or nothing" rule doesn't guess a port for generic Node


def test_generic_node_without_start_script_returns_none_all_or_nothing():
    scan = {"package_json": '{"dependencies": {"lodash": "1.0.0"}}'}
    assert detect_stack_from_rules(scan) is None


def test_requirements_txt_with_procfile_web_line_used_verbatim():
    scan = {"requirements_txt": True, "procfile": "web: gunicorn app:app\nworker: celery worker -A app"}
    result = detect_stack_from_rules(scan)
    assert result.build_cmd == "pip install -r requirements.txt"
    assert result.run_cmd == "gunicorn app:app"


def test_requirements_txt_with_manage_py_detected_as_django():
    scan = {"requirements_txt": True, "manage_py": True}
    result = detect_stack_from_rules(scan)
    assert "manage.py runserver 0.0.0.0:$PORT" in result.run_cmd


def test_requirements_txt_with_fastapi_app_py():
    scan = {"requirements_txt": True, "app_py": "from fastapi import FastAPI\napp = FastAPI()\n"}
    result = detect_stack_from_rules(scan)
    assert result.run_cmd == "uvicorn app:app --host 0.0.0.0 --port $PORT"


def test_requirements_txt_with_flask_main_py():
    scan = {"requirements_txt": True, "main_py": "from flask import Flask\napp = Flask(__name__)\n"}
    result = detect_stack_from_rules(scan)
    assert result.run_cmd == "flask --app main run --host 0.0.0.0 --port $PORT"


def test_requirements_txt_with_no_recognizable_entrypoint_returns_none():
    scan = {"requirements_txt": True}
    assert detect_stack_from_rules(scan) is None


def test_no_recognizable_files_at_all_returns_none():
    assert detect_stack_from_rules({}) is None


def test_procfile_present_but_no_web_line_falls_through_to_none():
    scan = {"requirements_txt": True, "procfile": "worker: celery worker -A app"}
    assert detect_stack_from_rules(scan) is None


# ---------------------------------------------------------------------------
# §23.5 — LLM fallback response parsing
# ---------------------------------------------------------------------------


def test_stack_detection_response_parses_valid_json():
    result = parse_stack_detection_response('{"build_cmd": "pip install -r requirements.txt", "run_cmd": "python x.py", "port": 8080}')
    assert result.stack == "llm_fallback"
    assert result.port == 8080


def test_stack_detection_response_strips_markdown_fence():
    result = parse_stack_detection_response('```json\n{"build_cmd": null, "run_cmd": "node x.js", "port": 4000}\n```')
    assert result.build_cmd is None
    assert result.port == 4000


def test_stack_detection_response_rejects_non_json():
    try:
        parse_stack_detection_response("not json")
        assert False, "expected DetectionLlmError"
    except DetectionLlmError:
        pass


def test_stack_detection_response_rejects_missing_run_cmd():
    try:
        parse_stack_detection_response('{"build_cmd": "x", "port": 3000}')
        assert False
    except DetectionLlmError:
        pass


def test_stack_detection_response_rejects_non_integer_port():
    try:
        parse_stack_detection_response('{"run_cmd": "x", "port": "not-an-int"}')
        assert False
    except DetectionLlmError:
        pass


def test_stack_detection_response_rejects_boolean_port():
    # bool is a subclass of int in Python — worth its own case so a stray
    # `"port": true` from the model doesn't silently pass as port 1.
    try:
        parse_stack_detection_response('{"run_cmd": "x", "port": true}')
        assert False
    except DetectionLlmError:
        pass


# ---------------------------------------------------------------------------
# §23.6 — monorepo root detection
# ---------------------------------------------------------------------------


def test_single_package_json_at_root_is_ordinary_single_target():
    result = propose_roots_from_markers(["package.json"])
    assert result == [DeployTargetProposal(name="app", root=".")]


def test_no_markers_at_all_is_ordinary_single_target():
    result = propose_roots_from_markers([])
    assert result == [DeployTargetProposal(name="app", root=".")]


def test_two_roots_at_different_depths_resolved_without_llm():
    result = propose_roots_from_markers(["apps/web/package.json", "apps/api/requirements.txt"])
    assert {t.root for t in result} == {"apps/web", "apps/api"}
    assert {t.name for t in result} == {"web", "api"}


def test_root_level_marker_alongside_subdir_markers_not_counted_as_a_third_root():
    # A workspace-root package.json coexisting with two real per-package
    # roots shouldn't itself become a third proposed target.
    result = propose_roots_from_markers(["package.json", "apps/web/package.json", "apps/api/package.json"])
    assert {t.root for t in result} == {"apps/web", "apps/api"}


def test_monorepo_marker_with_only_one_candidate_is_ambiguous_needs_llm():
    result = propose_roots_from_markers(["turbo.json", "apps/web/package.json"])
    assert result is None


def test_monorepo_marker_with_zero_candidates_is_ambiguous_needs_llm():
    result = propose_roots_from_markers(["pnpm-workspace.yaml"])
    assert result is None


def test_single_nested_root_no_monorepo_marker_resolved_without_llm():
    result = propose_roots_from_markers(["server/package.json"])
    assert result == [DeployTargetProposal(name="server", root="server")]


def test_root_proposal_response_parses_valid_json():
    result = parse_root_proposal_response('{"targets": [{"name": "frontend", "root": "apps/web"}, {"name": "backend", "root": "apps/api"}]}')
    assert len(result) == 2
    assert result[0] == DeployTargetProposal(name="frontend", root="apps/web")


def test_root_proposal_response_rejects_empty_targets_list():
    try:
        parse_root_proposal_response('{"targets": []}')
        assert False
    except DetectionLlmError:
        pass


def test_root_proposal_response_rejects_duplicate_names():
    try:
        parse_root_proposal_response('{"targets": [{"name": "a", "root": "x"}, {"name": "a", "root": "y"}]}')
        assert False
    except DetectionLlmError:
        pass


def test_root_proposal_response_rejects_blank_root():
    try:
        parse_root_proposal_response('{"targets": [{"name": "a", "root": "  "}]}')
        assert False
    except DetectionLlmError:
        pass
