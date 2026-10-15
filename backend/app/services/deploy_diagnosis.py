"""
§23.9 points 2 and 4 — deploy failure diagnosis.

A single tool-less LLM call, same shape as memory_extraction.py's own calls
(`llm_client.call_llm(messages, tools=[], credential=credential)`): "not just
reformatting the raw error — producing a human-readable explanation plus a
suggested fix prompt... text only." Unlike memory_extraction.py's calls,
this one needs *structured* output (a diagnosis is useless to §23.9 point 4's
build-vs-environment branching unless the failure_class comes back as a
value the caller can switch on, not prose it has to re-parse) — see
deploy_detection.py's own JSON-fallback calls for the same "ask for strict
JSON, defensively strip a markdown fence, raise a clear error on anything
else" shape this reuses via parse_json_object.

Best-effort, matching memory_extraction.py's own reasoning: a diagnosis that
fails to produce is not a reason to hide the raw log §23.9 point 1 already
captured and displayed. deploy_pipeline.py calls this only after a deploy_run
has already been written with its raw stdout/stderr/exit_code — a
DiagnosisLlmError or LlmCallFailedError here just leaves diagnosis_text/
failure_class/suggested_fix_prompt null on an otherwise-complete row, never
blocks the Console tab from showing what already ran.
"""
from dataclasses import dataclass

from app.services import llm_client
from app.services.deploy_detection import DetectionLlmError, parse_json_object

_ENVIRONMENT_KINDS = ("secrets", "cors", "oauth", "database", "other")

# §23.9 point 4's own two examples, given verbatim so the model classifies
# against the same vocabulary the UI branches on, not its own paraphrase of it.
_ENVIRONMENT_EXAMPLES = "missing secrets, CORS misconfiguration, a database that's unreachable"


class DiagnosisLlmError(ValueError):
    """The diagnosis call's response isn't the structured JSON this module
    requires. Distinct from deploy_detection.DetectionLlmError (different
    module, different caller-facing meaning) even though both wrap the same
    underlying JSON-parsing helper."""


@dataclass
class DeployDiagnosis:
    diagnosis_text: str
    failure_class: str  # 'build' | 'environment'
    suggested_fix_prompt: str | None  # always None when failure_class == 'environment'
    # Phase 5.4: which of §23.8's known preview limitations an *environment* failure
    # looks like — 'secrets' | 'cors' | 'oauth' | 'database' | 'other'. None for a
    # build-class failure. Routes the failure to the matching notification.
    environment_kind: str | None = None


def build_diagnosis_prompt(phase: str, build_cmd: str | None, run_cmd: str | None, stdout: str, stderr: str, exit_code: int | None) -> str:
    """`phase` is the deploy_run's own 'build' or 'start' — which command
    actually produced this log matters to the model (a build-phase failure
    and a start-phase failure read very differently even with similar-looking
    output), so it's given explicitly rather than left to be inferred from
    the log text alone."""
    command = build_cmd if phase == "build" else run_cmd
    return (
        "A deployment just failed. You cannot run any command yourself — respond "
        "with ONLY a JSON object, no markdown fences, no other text.\n\n"
        f"Failed phase: {phase}\n"
        f"Command that failed: {command or '(unknown)'}\n"
        f"Exit code: {exit_code if exit_code is not None else '(unknown)'}\n\n"
        f"--- stdout ---\n{stdout or '(empty)'}\n\n"
        f"--- stderr ---\n{stderr or '(empty)'}\n\n"
        "Diagnose the root cause in plain language a developer can act on immediately "
        "— don't just reformat the log. Then classify it as exactly one of:\n"
        '  "build" — the app\'s own code doesn\'t run (a real bug: a syntax error, a '
        "missing import, a failing test, a type error, and so on).\n"
        f'  "environment" — not a code bug ({_ENVIRONMENT_EXAMPLES}, or similar).\n\n'
        'If (and only if) it is "environment", also say which kind, as exactly one of:\n'
        '  "secrets" — an API key, token or environment variable the app needs is missing or unset.\n'
        '  "cors" — a browser request was blocked because the backend doesn\'t allow this origin.\n'
        '  "oauth" — a sign-in redirect/callback URL isn\'t registered with the identity provider.\n'
        '  "database" — a database or other data store is unreachable (IP allow-list, private network, wrong host).\n'
        '  "other" — an environment problem that is none of the above.\n\n'
        "Respond with exactly this shape:\n"
        '{"diagnosis": "<2-4 sentence explanation of what actually went wrong>", '
        '"failure_class": "build" | "environment", '
        '"environment_kind": "secrets" | "cors" | "oauth" | "database" | "other" | null, '
        '"suggested_fix_prompt": "<a short instruction the person could hand back to a coding agent '
        'to fix this, or null if failure_class is \\"environment\\" — never suggest a code fix for an '
        'environment issue>"}\n'
        'environment_kind must be null whenever failure_class is "build".'
    )


def parse_diagnosis_response(text: str) -> DeployDiagnosis:
    try:
        data = parse_json_object(text)
    except DetectionLlmError as exc:
        raise DiagnosisLlmError(str(exc)) from exc

    diagnosis = data.get("diagnosis")
    failure_class = data.get("failure_class")
    suggested_fix_prompt = data.get("suggested_fix_prompt")

    if not isinstance(diagnosis, str) or not diagnosis.strip():
        raise DiagnosisLlmError("Diagnosis response is missing a non-empty 'diagnosis' string.")
    if failure_class not in ("build", "environment"):
        raise DiagnosisLlmError("Diagnosis response's failure_class must be 'build' or 'environment'.")
    if suggested_fix_prompt is not None and not isinstance(suggested_fix_prompt, str):
        raise DiagnosisLlmError("Diagnosis response's suggested_fix_prompt must be a string or null.")

    # §23.9 point 4: "Never use 'fix' framing" for an environment issue —
    # enforced here rather than trusted from the model's own response, since
    # a model that got failure_class right but still filled in a fix prompt
    # out of habit must not be allowed to leak "fix"-framed UI for a
    # not-a-code-bug failure. A build-class response with no suggested fix
    # is left as None too (a diagnosis without an actionable next step is
    # still a valid diagnosis) rather than defaulted to something invented
    # here.
    if failure_class == "environment":
        suggested_fix_prompt = None
    elif suggested_fix_prompt is not None:
        suggested_fix_prompt = suggested_fix_prompt.strip() or None

    # Phase 5.4: optional, and deliberately lenient — a model that classified the
    # failure correctly but fumbled this extra field shouldn't lose the whole
    # diagnosis. Anything unrecognised on an environment failure becomes "other".
    environment_kind = None
    if failure_class == "environment":
        raw_kind = data.get("environment_kind")
        environment_kind = raw_kind if raw_kind in _ENVIRONMENT_KINDS else "other"

    return DeployDiagnosis(
        diagnosis_text=diagnosis.strip(),
        failure_class=failure_class,
        suggested_fix_prompt=suggested_fix_prompt,
        environment_kind=environment_kind,
    )


async def diagnose(
    phase: str,
    build_cmd: str | None,
    run_cmd: str | None,
    stdout: str,
    stderr: str,
    exit_code: int | None,
    credential: llm_client.ResolvedCredential,
) -> DeployDiagnosis:
    prompt = build_diagnosis_prompt(phase, build_cmd, run_cmd, stdout, stderr, exit_code)
    response = await llm_client.call_llm([{"role": "user", "content": prompt}], tools=[], credential=credential)
    return parse_diagnosis_response(response.text)
