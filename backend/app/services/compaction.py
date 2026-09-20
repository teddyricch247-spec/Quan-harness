"""
§17.1 — Context compaction. Implementation order step 9.

`should_compact` is pure and unit-tested directly. The actual compaction call
(app/services/agent_loop.py's `maybe_compact`) is the I/O shell around it —
same split as file_tools.py/text_edit.py: the graded decision lives here,
free of app.config/app.db/httpx/the LLM client, so it's testable without a
credential or a network call.

The instruction text and re-injection framing below are reproduced close to
verbatim from DeepSeek Harness's `dsh-compaction-basic` package (MIT
License), adapted only for this product's `update_plan` naming in place of
DSH's `todo_write` — see NOTICES.md for the full attribution entry this
phase adds.
"""
from dataclasses import dataclass

from app.services.token_estimate import estimate_tokens

COMPACTION_THRESHOLD = 0.70

COMPACTION_INSTRUCTION = """You are now acting as a compaction engine for this AI coding assistant.
Condense the conversation ABOVE into a structured checkpoint that lets
another model resume the work with no loss of essential context.

Output EXACTLY the Markdown structure below: keep every section, in
order. Use terse bullets, not prose paragraphs. Write "(none)" for an
empty section -- never drop a section.

## Primary Request and Intent
- [the user's original and evolving goals; quote verbatim where the
  exact wording matters]

## Key Technical Concepts
- [technologies, frameworks, patterns, and conventions in play]

## Files and Code
- [exact path: why it matters, key changes or snippets]

## Errors and Fixes
- [error: how it was resolved, plus any related user feedback]

## Pending Jobs
- [explicitly requested work not yet completed]

## Current Work
- [precisely what was in progress at this checkpoint]

## Task List
- [the current plan state verbatim, if any -- pending / in progress / done]

## Next Step
- [the single next action, directly in line with the most recent
  request, or "(none)"]

## Critical Context
- [decisions and their rationale, constraints, user preferences, open
  questions, data needed to continue]

Rules:
- Write concise English engineering prose. Preserve exact file paths,
  commands, error strings, identifiers, numeric values, function
  signatures, and syntax fragments.
- Capture user feedback and explicit instructions faithfully, especially
  corrections.
- Do NOT mention this summarization request or that the context was
  compacted.
- Output only the checkpoint text: do not call any tool or take any
  other action.
- If the conversation already contains a <compacted-summary> block, it
  is a PRIOR checkpoint. Do not copy it forward verbatim: preserve
  still-true facts, drop stale ones, and merge newer information into a
  single consolidated summary under the same structure."""

_REINJECTION_TEMPLATE = """This is an automatically generated checkpoint condensing an earlier span
of the conversation to free up context. Treat the captured context as
established background and build on it without restating it. Continue
the task directly from the messages that follow, without acknowledging
this checkpoint.

<compacted-summary>
{checkpoint_text}
</compacted-summary>"""


def should_compact(token_count: int, context_window: int, threshold: float = COMPACTION_THRESHOLD) -> bool:
    """§17.1: 'Once the running token count for the assembled message list
    crosses roughly 70% of the active model's context window, compact.'"""
    if context_window <= 0:
        return False
    return token_count >= context_window * threshold


def wrap_checkpoint(checkpoint_text: str) -> str:
    """The re-injection framing — replaces the condensed span as a synthesized
    user message."""
    return _REINJECTION_TEMPLATE.format(checkpoint_text=checkpoint_text.strip())


@dataclass
class CompactionPlan:
    """What agent_loop.py needs to actually build the auxiliary call: the
    index (into the full per-session message list) of the first message to
    keep verbatim, and everything before it gets replaced by the wrapped
    checkpoint. §17.1: 'Keep at least the most recent full step's tool
    results verbatim regardless of budget pressure' — kept_from_index is
    chosen by the caller to satisfy that, not by this dataclass."""

    kept_from_index: int
    estimated_tokens_freed: int


def plan_compaction(message_texts: list[str], kept_from_index: int) -> CompactionPlan:
    """`message_texts` is the plain-text rendering of each message in the
    dynamic conversation-history portion of context assembly (§17 item 6) —
    never the static system prompt/memory portion, which §17.1 says is never
    summarized. `kept_from_index` is the caller's chosen boundary (at least
    the most recent full step, per the rule above)."""
    freed = sum(estimate_tokens(t) for t in message_texts[:kept_from_index])
    return CompactionPlan(kept_from_index=kept_from_index, estimated_tokens_freed=freed)
