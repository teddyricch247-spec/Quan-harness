"""
§20 — Memory System. Implementation order step 11.

Pure prompt-building and budget-enforcement only — no I/O, no LLM call, no
repository import, same pure-core/imperative-shell split every decision
module in this codebase follows (PHASE3_NOTES.md's closing note names the
convention explicitly). The I/O shell that resolves a real memory_md, calls
the LLM through these prompts, and writes the result back lives in
app/services/memory_extraction.py; the shell that *renders* an already-
resolved memory_md into the system prompt's WHAT_YOU_KNOW_ABOUT_* dynamic
sections lives in system_prompt.py itself, alongside its other
format_*() dynamic-section renderers — this module only ever builds the
prompt text for the extraction call, nothing about the turn's own prompt.

Two revision prompts, one per tier §20 describes:
  - build_project_memory_revision_prompt — project_memory.memory_md, revised
    through the project's own resolved LLM credential after every completed
    or stuck turn.
  - build_user_memory_revision_prompt — build_user_memory.memory_md, the
    smaller parallel call that's explicitly allowed to return the existing
    memory unchanged ("most turns reveal nothing account-level").

Both prompts ask for the complete replacement text, not a diff — §20 is
explicit that this is "an update, not an append": "preserve what's still
relevant, add new durable facts, remove what this turn made obsolete."
"""

# §20: "stay within roughly 4,000 characters" — given to the model as a
# target in the prompt itself, not enforced by truncating its output (a
# truncated-mid-sentence memory_md would be worse than a slightly-over-budget
# one). MEMORY_HARD_CAP below is the separate, defensive backstop.
MEMORY_CHAR_BUDGET = 4000

# A hard ceiling enforced on the *response*, regardless of what the prompt
# asked for — the same defensive posture this codebase takes everywhere a
# model's own output feeds back into something structural (audit_log's
# output_summary truncated to 500 chars in agent_loop.py; compaction's own
# checkpoint text has no such cap because it's shown to a person as
# transcript content, not stored as a standing system-prompt fixture the way
# memory_md is). A malformed or runaway response degrades to "memory got
# truncated this round," never to an ever-growing system prompt.
MEMORY_HARD_CAP = 8000

_TRUNCATION_NOTICE = "\n\n[memory truncated — the last extraction call's response exceeded the size limit]"


PROJECT_MEMORY_INSTRUCTIONS = f"""You maintain a short, durable memory file for one specific software project, \
built from what an autonomous coding agent has learned while working in it — build quirks, conventions the \
codebase actually follows, decisions already made and why, anything worth a future session not re-discovering \
from scratch. This is not a log of what happened; it's a curated index of what's still true and useful going \
forward.

You will be given the current memory file (it may be empty, if this is the project's first extraction) and the \
final report from a turn that just completed or got stuck. Produce the complete, revised memory file:
- Preserve whatever in the current memory is still relevant.
- Add any new durable fact this turn's report reveals.
- Remove anything this turn's report makes obsolete or corrects.
- Stay within roughly {MEMORY_CHAR_BUDGET} characters.
- If this turn's report reveals nothing worth remembering, return the current memory file unchanged.

Respond with only the revised memory file's text — no preamble, no explanation, no markdown code fence around \
the whole thing."""


BUILD_USER_MEMORY_INSTRUCTIONS = f"""You maintain a short, durable memory file of one person's general \
preferences and working habits — the kind of thing that holds across every software project they work on with \
an autonomous coding agent, not anything specific to one project. Most turns reveal nothing at this level; \
returning the memory file completely unchanged is the normal, expected outcome, not a failure.

You will be given the current memory file (it may be empty) and the final report from a turn that just \
completed or got stuck in one of this person's projects. Only revise the memory file if this turn's report \
reveals something genuinely account-level and durable — a stated general preference, a working style, \
something that would hold in a different project too. Project-specific detail (a file path, a library choice \
for this one codebase, a bug fixed in this one project) does not belong here even if it's the only thing the \
report contains — leave the memory file unchanged in that case.

If you do revise it: preserve what's still relevant, add the new fact, remove anything obsolete, stay within \
roughly {MEMORY_CHAR_BUDGET} characters. Respond with only the memory file's text (the current one, unchanged, \
if nothing qualifies) — no preamble, no explanation, no markdown code fence around the whole thing."""


def _build_revision_prompt(instructions: str, current_memory_md: str, turn_report: str) -> str:
    current = current_memory_md.strip() or "(empty — nothing recorded yet)"
    return (
        f"{instructions}\n\n"
        f"--- CURRENT MEMORY FILE ---\n{current}\n--- END CURRENT MEMORY FILE ---\n\n"
        f"--- THIS TURN'S FINAL REPORT ---\n{turn_report.strip()}\n--- END THIS TURN'S FINAL REPORT ---"
    )


def build_project_memory_revision_prompt(current_memory_md: str, turn_report: str) -> str:
    return _build_revision_prompt(PROJECT_MEMORY_INSTRUCTIONS, current_memory_md, turn_report)


def build_user_memory_revision_prompt(current_user_memory_md: str, turn_report: str) -> str:
    return _build_revision_prompt(BUILD_USER_MEMORY_INSTRUCTIONS, current_user_memory_md, turn_report)


def enforce_char_budget(memory_md: str, limit: int = MEMORY_HARD_CAP) -> str:
    """Defensive-only backstop against a malformed or runaway extraction
    response — see MEMORY_HARD_CAP's own docstring. Truncates at the last
    paragraph break before `limit` where one exists (cleaner than a mid-
    sentence cut), otherwise at a hard character boundary, and appends a
    plain notice so a person looking at their own memory later isn't
    confused by a sentence that just stops. A no-op well under the limit,
    which is the overwhelmingly common case."""
    if len(memory_md) <= limit:
        return memory_md
    budget = limit - len(_TRUNCATION_NOTICE)
    if budget <= 0:
        return memory_md[:limit]
    cut = memory_md.rfind("\n\n", 0, budget)
    if cut == -1 or cut < budget // 2:
        cut = budget
    return memory_md[:cut].rstrip() + _TRUNCATION_NOTICE
