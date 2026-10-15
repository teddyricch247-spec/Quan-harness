"""
§19 — Stuck Detection. Implementation order step 9.

Evaluated against the CURRENT turn loop's own tool-call history only (§16.2's
turn loop resets its event list at the start of every fresh turn) — never the
whole session's history, so a legitimate repeated pattern spanning two
different tasks handled earlier in the same session never trips it.

Kept dependency-free deliberately, the same reasoning as guard_rules.py and
checkpoint_fifo.py: this is graded, load-bearing decision logic ("stop the
agent" / "don't"), so it needs to be unit-testable without a database or an
LLM credential. app/services/agent_loop.py is the only caller — it builds the
StuckEvent list from the real tool_call/tool_result pairs each turn and holds
the one piece of state that genuinely can't be derived from the event list
alone (`already_soft_nudged_this_turn`), the same way §16.2's own pseudocode
holds `already_nudged_this_turn` as a plain loop-local variable for the
lint/test reminder rather than trying to derive it from the log.

Recomputes from the full turn-scoped event list on every call rather than
carrying incremental state — consistent with §16.1's own "session state is
always derived by reading the log, never held only in memory" principle, and
cheap in practice since a turn's own event list is bounded by
`max_turn_iterations` (default 50, §16.2).
"""
import hashlib
import json
from dataclasses import dataclass

SOFT_WARNING_AUTO_CALL_THRESHOLD = 15
_EDIT_TOOLS = frozenset({"str_replace", "create_file"})


@dataclass(frozen=True)
class StuckEvent:
    """One tool_call/tool_result pair from the current turn, reduced to the
    meaningful-content form the detector compares — never a raw event row
    (those carry a database id and a timestamp that differ every time even
    when nothing that matters changed, which §19 explicitly says not to
    compare on)."""

    tool: str
    args_key: str  # normalize_args() below — never a raw dict (dict ordering/whitespace shouldn't matter)
    result_key: str  # normalize_result() below
    success: bool
    file_path: str | None = None  # set for str_replace/create_file only
    content_hash: str | None = None  # sha256 of the file's content immediately after this edit


@dataclass
class StuckCheck:
    hard_stop: bool = False
    soft_warning: bool = False
    explanation: str | None = None


def normalize_args(tool: str, args: dict) -> str:
    """Meaningful-content key for a tool call's arguments. Plain
    `json.dumps(args, sort_keys=True)` for everything — every current tool's
    arguments (§14) are already the meaningful content themselves, with no
    per-call random id/nonce field to strip out."""
    return json.dumps(args, sort_keys=True, default=str)


def normalize_result(tool: str, *, ok: bool, content: str = "", error: str = "") -> str:
    """Meaningful-content key for what a tool call returned. Hashed rather than
    stored verbatim — a view_file result can be arbitrarily large, and only
    whether two results are the *same* matters here, never their content."""
    payload = content if ok else error
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def _same_call(a: StuckEvent, b: StuckEvent) -> bool:
    return a.tool == b.tool and a.args_key == b.args_key


def _same_call_and_result(a: StuckEvent, b: StuckEvent) -> bool:
    return _same_call(a, b) and a.result_key == b.result_key


def _trailing_run_length(events: list[StuckEvent]) -> int:
    """How many trailing events are all the same call-and-result as the very
    last one. 1 if the list is empty or the last event is unique so far."""
    if not events:
        return 0
    last = events[-1]
    run = 0
    for event in reversed(events):
        if _same_call_and_result(event, last):
            run += 1
        else:
            break
    return run


def _check_repeating_call_and_result(events: list[StuckEvent]) -> str | None:
    """Signal 1: the same tool call (by meaningful content) produces the same
    result three times in a row — regardless of success/failure. Signal 3
    below is the failure-specific variant with its grace nudge; this one is
    the general case (e.g. a read-only call the model keeps re-issuing)."""
    if _trailing_run_length(events) >= 3:
        last = events[-1]
        return f"The same `{last.tool}` call produced the same result three times in a row."
    return None


def _check_repeating_error(events: list[StuckEvent]) -> tuple[bool, str | None]:
    """Signal 3. Returns (hard_stop, soft_nudge_text). A run of exactly 2
    identical failing calls asks for a one-time nudge; a run of 3+ is the hard
    stop. Never fires both in the same check — by the time the run reaches 3,
    the nudge for the run-of-2 moment has already happened on a prior call."""
    if not events or events[-1].success:
        return False, None
    run = _trailing_run_length(events)
    if run >= 3:
        return True, None
    if run == 2:
        return False, (
            "Repeating the exact same call again will not work — review the error "
            "and either correct the arguments or try a different approach."
        )
    return False, None


def _check_edit_revert_cycle(events: list[StuckEvent]) -> str | None:
    """Signal 2: for some file this turn, a new edit's content hash matches a
    hash that file already had earlier in this same turn — and that's
    happened twice. Tracks per-file hash history in the order edits actually
    happened; only str_replace/create_file events carry a content_hash."""
    seen_by_file: dict[str, list[str]] = {}
    revert_counts: dict[str, int] = {}
    for event in events:
        if event.file_path is None or event.content_hash is None or not event.success:
            continue
        history = seen_by_file.setdefault(event.file_path, [])
        if event.content_hash in history:
            revert_counts[event.file_path] = revert_counts.get(event.file_path, 0) + 1
            if revert_counts[event.file_path] >= 2:
                return f"`{event.file_path}` has returned to a content state it already had earlier this turn, twice."
        history.append(event.content_hash)
    return None


def _check_alternating_pattern(events: list[StuckEvent]) -> str | None:
    """Signal 4: A-B-A-B across the last four events, where A and B are
    genuinely different calls — two full cycles, four events total."""
    if len(events) < 4:
        return None
    a1, b1, a2, b2 = events[-4], events[-3], events[-2], events[-1]
    if _same_call_and_result(a1, a2) and _same_call_and_result(b1, b2) and not _same_call(a1, b1):
        return f"Alternating between `{a1.tool}` and `{b1.tool}` with no progress — two full cycles with no new outcome."
    return None


def _check_soft_warning(events: list[StuckEvent], already_soft_nudged_this_turn: bool) -> str | None:
    """More than 15 consecutive Auto tool calls with no str_replace/create_file
    among them. `already_soft_nudged_this_turn` is owned by the caller (see
    module docstring) — this only ever proposes firing once."""
    if already_soft_nudged_this_turn:
        return None
    if len(events) <= SOFT_WARNING_AUTO_CALL_THRESHOLD:
        return None
    trailing = events[-(SOFT_WARNING_AUTO_CALL_THRESHOLD + 1):]
    if any(e.tool in _EDIT_TOOLS for e in trailing):
        return None
    return (
        f"You've made {len(trailing)} tool calls without editing any file. Make a "
        "concrete change now, or explain plainly why you're still investigating."
    )


def run_stuck_detector(events: list[StuckEvent], already_soft_nudged_this_turn: bool = False) -> StuckCheck:
    """The single entry point `agent_loop.py` calls after every Auto tool call,
    per §16.2's pseudocode. Hard-stop signals are checked in the order §19
    lists them; the first one that matches wins (they're evaluated on the same
    trailing events, so more than one can technically be true at once — the
    person only needs to know one reason, not an exhaustive list)."""
    if not events:
        return StuckCheck()

    explanation = _check_repeating_call_and_result(events)
    if explanation:
        return StuckCheck(hard_stop=True, explanation=explanation)

    hard_stop, nudge = _check_repeating_error(events)
    if hard_stop:
        last = events[-1]
        return StuckCheck(hard_stop=True, explanation=f"The same `{last.tool}` call has now failed three times in a row.")
    if nudge:
        return StuckCheck(soft_warning=True, explanation=nudge)

    explanation = _check_edit_revert_cycle(events)
    if explanation:
        return StuckCheck(hard_stop=True, explanation=explanation)

    explanation = _check_alternating_pattern(events)
    if explanation:
        return StuckCheck(hard_stop=True, explanation=explanation)

    explanation = _check_soft_warning(events, already_soft_nudged_this_turn)
    if explanation:
        return StuckCheck(soft_warning=True, explanation=explanation)

    return StuckCheck()
