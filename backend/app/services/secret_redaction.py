"""
§23.10: preview secrets are "never placed into the LLM's context in raw form,
and never readable or usable by the agent." Pure, dependency-free redaction
(same "no app.config/app.db imports so it's unit-testable in isolation" rule as
guard_rules.py) — app/services/preview_secrets_service.py is the I/O shell that
feeds it real values.

Where this is applied (the point of having one shared function):
  - agent_loop._execute_call — the single chokepoint every tool result passes
    through on its way into the transcript, and so into the model's context.
    Whatever a tool managed to read from the workspace, a preview secret's value
    doesn't survive that boundary.
  - deploy_pipeline — build/start logs are stored on deploy_runs, shown to the
    person, AND fed to the diagnosis LLM call and (via DEPLOY_DIAGNOSIS) the main
    agent's next turn. A crashing app that prints its own environment would
    otherwise walk a secret straight into all three.

What this is and isn't. It matches the *exact* value (plus its URL-encoded and
base64 forms, since logs commonly show those). It is a containment layer, not a
proof: a value the agent deliberately re-encodes some other way (hex, split
across lines, reversed) would not be caught. The stronger guarantees live
elsewhere — the values are stored apart from anything the agent can query, are
never returned by any API, and never enter a prompt — and this is the backstop
if one of those boundaries is somehow crossed by accident. See
docs/PHASE5_3_5_4_NOTES.md's "What 'the agent cannot read' does and doesn't
mean" for the honest boundary.
"""
import base64
import urllib.parse

REDACTED = "<secret-hidden>"

# Below this length a value is too likely to collide with ordinary text to
# redact blindly (a "secret" of "1" would shred every log line containing a 1).
MIN_REDACT_LENGTH = 4

# Environment variables people legitimately put in a key/value panel whose
# *values* are ordinary words that appear all over any log. Redacting these would
# make logs unreadable without protecting anything. Compared case-insensitively.
_TRIVIAL_VALUES = frozenset(
    {
        "true", "false", "null", "none", "test", "tests", "dev", "prod", "production",
        "development", "staging", "local", "localhost", "debug", "info", "warn",
        "warning", "error", "yes", "no", "on", "off", "enabled", "disabled",
    }
)


def _variants(value: str) -> list[str]:
    forms = {value}
    quoted = urllib.parse.quote(value, safe="")
    forms.add(quoted)
    forms.add(urllib.parse.quote_plus(value))
    raw = value.encode("utf-8", errors="ignore")
    forms.add(base64.b64encode(raw).decode("ascii"))
    forms.add(base64.urlsafe_b64encode(raw).decode("ascii"))
    forms.add(base64.b64encode(raw).decode("ascii").rstrip("="))
    return [f for f in forms if len(f) >= MIN_REDACT_LENGTH]


def redactable_values(values: dict[str, str] | list[str]) -> list[str]:
    """The strings to search for, longest first (so a value that contains another
    is replaced whole rather than leaving a fragment behind)."""
    raw = list(values.values()) if isinstance(values, dict) else list(values)
    needles: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or len(value) < MIN_REDACT_LENGTH:
            continue
        if value.strip().lower() in _TRIVIAL_VALUES:
            continue
        needles.update(_variants(value))
    return sorted(needles, key=len, reverse=True)


def redact(text: str | None, values: dict[str, str] | list[str]) -> str | None:
    if not text:
        return text
    redacted = text
    for needle in redactable_values(values):
        if needle in redacted:
            redacted = redacted.replace(needle, REDACTED)
    return redacted
