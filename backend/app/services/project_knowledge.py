"""
§21 — Project Knowledge. Implementation order step 12.

Pure trigger-matching and selection logic — no I/O, same split as every
other decision module here (see memory.py's own docstring for the fuller
statement of the convention). The I/O shell — fetching a project's notes,
reconstructing which have already triggered this session, appending the
bookkeeping event, and folding the result into the turn's dynamic sections —
lives in agent_loop.py, the same place repo_map/project_secrets/current_plan
are already gathered each iteration; rendering an already-selected list of
notes into system-prompt text is system_prompt.format_project_knowledge,
alongside its other dynamic-section renderers.

§21's own two trigger kinds, verbatim: "a keyword trigger (a word/phrase —
if it appears in the task or a file the agent touches, the note is pulled
in) or a path trigger (a glob pattern — if the agent opens a matching
file)." Two design decisions §21's own text leaves open, both made here:

- "A file the agent touches" is read as *the path* of a file the agent has
  viewed or created this session (agent_loop.py's own `viewed_paths` —
  already exactly this signal, reconstructed from the event log the same
  way for repo_map's ranking and for str_replace's "must be viewed first"
  gate), not a scan of that file's *content*. §21's own worked example
  ("auth/README", keyword trigger "auth") reads equally well either way,
  but scanning viewed/created file content for a keyword substring on every
  tool result would be real, ongoing per-file work with no existing
  precedent in this codebase (viewed_paths is a set of strings, not a
  content cache) — matching against paths already agent_loop.py tracks for
  other reasons is the smaller, more defensible surface.
- "The task" is read as the same signal repo_map's own keyword ranking
  already uses for an identical purpose (agent_loop._latest_user_text): the
  most recent user-authored text, a fresh message or a mid-run interrupt,
  not the original session-opening message specifically — a note relevant
  to what the person is asking for *right now* should be able to trigger
  even several turns into a session, not only on turn one.
"""
import fnmatch
from dataclasses import dataclass


@dataclass
class ProjectKnowledgeNote:
    id: str
    name: str
    body: str
    trigger_type: str  # "keyword" | "path"
    trigger_value: str


def note_from_row(row: dict) -> ProjectKnowledgeNote:
    return ProjectKnowledgeNote(
        id=row["id"],
        name=row["name"],
        body=row["body"],
        trigger_type=row["trigger_type"],
        trigger_value=row["trigger_value"],
    )


def _keyword_triggers(trigger_value: str, task_text: str, touched_paths: set[str]) -> bool:
    needle = trigger_value.strip().lower()
    if not needle:
        return False
    if needle in task_text.lower():
        return True
    return any(needle in path.lower() for path in touched_paths)


def _path_triggers(trigger_value: str, touched_paths: set[str]) -> bool:
    """fnmatch.fnmatch alone requires a full-string match against the whole
    path from its root, which would make a pattern like "migrations/*.sql"
    (§21's own worked example) fire only on a path that is literally
    "migrations/<something>.sql" from the repo root — never on the far more
    typical "db/migrations/0007_x.sql" or "backend/db/migrations/x.sql". Real
    repos nest a migrations/ (or similar) directory below other folders far
    more often than not, so this also tries the pattern against every
    path-separator-aligned suffix of each touched path — the same "matches
    at any depth when the pattern has no leading slash" convention
    .gitignore-style tools already use, which is the closest existing mental
    model a person writing a trigger_value is likely to bring to this."""
    for path in touched_paths:
        if fnmatch.fnmatch(path, trigger_value):
            return True
        parts = path.split("/")
        if any(fnmatch.fnmatch("/".join(parts[i:]), trigger_value) for i in range(1, len(parts))):
            return True
    return False


def note_triggers(note: ProjectKnowledgeNote, task_text: str, touched_paths: set[str]) -> bool:
    if note.trigger_type == "keyword":
        return _keyword_triggers(note.trigger_value, task_text, touched_paths)
    if note.trigger_type == "path":
        return _path_triggers(note.trigger_value, touched_paths)
    return False  # an unrecognized trigger_type never fires rather than guessing


def select_newly_triggered(
    notes: list[ProjectKnowledgeNote],
    task_text: str,
    touched_paths: set[str],
    already_triggered_ids: set[str],
) -> list[ProjectKnowledgeNote]:
    """§21: "a note is only ever injected once per session, the first time it
    triggers." `already_triggered_ids` is reconstructed by the caller from
    this session's own event log (agent_loop._reconstruct_triggered_
    knowledge_ids) — never held only in local turn-loop state, for the same
    reason viewed_paths and crash-recovery's dangling-call scan aren't:
    _run_inner starts fresh on every resumed turn (a new message after
    'completed', a crash resume, an approval resume), and an in-memory-only
    set would forget everything an earlier turn of the same session already
    triggered, letting a note re-fire and re-bloat the prompt on turn two.
    Returns notes in their given order (creation order, as
    project_knowledge_repo.list_for_project already sorts) — stable and
    deterministic rather than alphabetical or trigger-type-grouped, since
    nothing about §21 asks for a particular presentation order among several
    notes triggering in the same iteration.

    This governs *when* a note fires and gets its bookkeeping event written
    — it is deliberately NOT what should be rendered into the turn's
    PROJECT_KNOWLEDGE dynamic section by itself. See select_all_triggered's
    own docstring for why the caller needs both."""
    return [
        note
        for note in notes
        if note.id not in already_triggered_ids and note_triggers(note, task_text, touched_paths)
    ]


def select_all_triggered(
    notes: list[ProjectKnowledgeNote],
    already_triggered_ids: set[str],
    newly_triggered: list[ProjectKnowledgeNote],
) -> list[ProjectKnowledgeNote]:
    """Every note that has triggered by this point in the session —
    `already_triggered_ids` (from earlier iterations, possibly earlier turns
    of the same session) plus `newly_triggered` (this iteration's own
    select_newly_triggered result) — in the notes' own given order.

    This is what agent_loop.py should actually render into PROJECT_KNOWLEDGE
    each iteration, not select_newly_triggered's own return value alone.
    "Only ever injected once per session" (§21) governs writing the
    bookkeeping event and stops a note from re-triggering — it does not mean
    the note should only be *visible to the model* for the single iteration
    it happens to trigger on. message_builder.build_messages explicitly
    skips project_knowledge_injected events when rendering conversation
    history (pure bookkeeping, never shown to the model), so a note's body
    text only ever reaches the model through this dynamic section — if that
    section were built from newly_triggered alone, a note would appear in
    the system prompt for exactly one LLM call and then vanish permanently
    for the rest of the session (since already-triggered notes can never
    re-fire), even though it may still be exactly as relevant on iteration
    ten as it was on iteration two. project_memory/build_user_memory stay
    part of every iteration's context once non-empty; a triggered Project
    Knowledge note is meant to behave the same way from the moment it first
    triggers onward, not flicker into view once and disappear."""
    triggered_ids = already_triggered_ids | {note.id for note in newly_triggered}
    return [note for note in notes if note.id in triggered_ids]
