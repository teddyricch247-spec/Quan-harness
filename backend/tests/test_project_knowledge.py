from app.services.project_knowledge import (
    ProjectKnowledgeNote,
    note_from_row,
    note_triggers,
    select_all_triggered,
    select_newly_triggered,
)


def _keyword_note(note_id="n1", value="auth"):
    return ProjectKnowledgeNote(id=note_id, name="Auth wrapper", body="custom auth wrapper, see auth/README", trigger_type="keyword", trigger_value=value)


def _path_note(note_id="n2", value="migrations/*.sql"):
    return ProjectKnowledgeNote(id=note_id, name="Migration naming", body="NNN_description.sql", trigger_type="path", trigger_value=value)


# --- note_from_row ---


def test_note_from_row_maps_every_field():
    row = {"id": "abc", "name": "N", "body": "B", "trigger_type": "keyword", "trigger_value": "v", "project_id": "p1", "created_at": "x", "updated_at": "y"}
    note = note_from_row(row)
    assert note == ProjectKnowledgeNote(id="abc", name="N", body="B", trigger_type="keyword", trigger_value="v")


# --- keyword trigger ---


def test_keyword_triggers_on_task_text():
    note = _keyword_note()
    assert note_triggers(note, task_text="please fix the auth flow", touched_paths=set())


def test_keyword_triggers_case_insensitively():
    note = _keyword_note()
    assert note_triggers(note, task_text="please fix the AUTH flow", touched_paths=set())


def test_keyword_does_not_trigger_on_unrelated_task_text():
    note = _keyword_note()
    assert not note_triggers(note, task_text="please fix the billing page", touched_paths=set())


def test_keyword_triggers_on_touched_path():
    note = _keyword_note()
    assert note_triggers(note, task_text="unrelated", touched_paths={"backend/app/auth/session.py"})


def test_keyword_triggers_on_touched_path_case_insensitively():
    note = _keyword_note()
    assert note_triggers(note, task_text="unrelated", touched_paths={"backend/app/AUTH/session.py"})


def test_keyword_does_not_trigger_on_unrelated_paths():
    note = _keyword_note()
    assert not note_triggers(note, task_text="unrelated", touched_paths={"backend/app/billing/session.py"})


def test_blank_keyword_never_triggers():
    note = _keyword_note(value="   ")
    assert not note_triggers(note, task_text="anything at all", touched_paths={"anything"})


# --- path trigger ---


def test_path_triggers_on_matching_glob():
    note = _path_note()
    assert note_triggers(note, task_text="", touched_paths={"db/migrations/0007_x.sql"})


def test_path_does_not_trigger_on_non_matching_path():
    note = _path_note()
    assert not note_triggers(note, task_text="", touched_paths={"db/seed.sql"})


def test_path_trigger_matches_nested_directory_by_default():
    """§21's own example ('migrations/*.sql') should fire on a realistic
    nested path, not only a literal repo-root 'migrations/*.sql' — see
    _path_triggers' own docstring for why."""
    note = _path_note()
    assert note_triggers(note, task_text="", touched_paths={"backend/db/migrations/0007_x.sql"})


def test_path_trigger_still_respects_the_pattern_itself():
    note = _path_note(value="migrations/*.sql")
    assert not note_triggers(note, task_text="", touched_paths={"backend/db/seeds/0007_x.sql"})


def test_path_trigger_ignores_task_text_entirely():
    """A glob pattern in the task text (unusual, but possible) must never
    substitute for an actual touched file — §21 ties path triggers to files
    the agent opens, not to what the person happened to type."""
    note = _path_note()
    assert not note_triggers(note, task_text="db/migrations/0007_x.sql", touched_paths=set())


def test_unrecognized_trigger_type_never_fires():
    note = ProjectKnowledgeNote(id="n3", name="x", body="y", trigger_type="regex", trigger_value=".*")
    assert not note_triggers(note, task_text="anything", touched_paths={"anything"})


# --- select_newly_triggered ---


def test_select_newly_triggered_returns_matching_notes():
    notes = [_keyword_note(), _path_note()]
    selected = select_newly_triggered(
        notes, task_text="working on auth today", touched_paths=set(), already_triggered_ids=set()
    )
    assert [n.id for n in selected] == ["n1"]


def test_select_newly_triggered_excludes_already_triggered():
    notes = [_keyword_note()]
    selected = select_newly_triggered(
        notes, task_text="auth again", touched_paths=set(), already_triggered_ids={"n1"}
    )
    assert selected == []


def test_select_newly_triggered_preserves_given_order():
    notes = [_path_note(), _keyword_note()]
    selected = select_newly_triggered(
        notes,
        task_text="auth",
        touched_paths={"db/migrations/0007_x.sql"},
        already_triggered_ids=set(),
    )
    assert [n.id for n in selected] == ["n2", "n1"]


def test_select_newly_triggered_empty_when_nothing_matches():
    notes = [_keyword_note(), _path_note()]
    selected = select_newly_triggered(
        notes, task_text="totally unrelated", touched_paths=set(), already_triggered_ids=set()
    )
    assert selected == []


# --- select_all_triggered ---
# Regression coverage for the bug this fix addresses: PROJECT_KNOWLEDGE must
# stay populated with every note that has ever triggered this session, not
# just whatever triggered on the current iteration — otherwise a note's
# content reaches the model for exactly one LLM call (the iteration it
# first fires on) and then permanently disappears, even though it's
# permanently marked "already triggered" and can never fire again.


def test_select_all_triggered_includes_previously_triggered_notes_with_nothing_new():
    """The core regression case: nothing triggers *this* iteration, but a
    note triggered on an earlier one — it must still be rendered."""
    notes = [_keyword_note()]
    all_triggered = select_all_triggered(notes, already_triggered_ids={"n1"}, newly_triggered=[])
    assert [n.id for n in all_triggered] == ["n1"]


def test_select_all_triggered_includes_newly_triggered_notes():
    notes = [_keyword_note()]
    all_triggered = select_all_triggered(notes, already_triggered_ids=set(), newly_triggered=notes)
    assert [n.id for n in all_triggered] == ["n1"]


def test_select_all_triggered_unions_already_and_newly_triggered():
    already = _path_note()
    new = _keyword_note()
    notes = [already, new]
    all_triggered = select_all_triggered(notes, already_triggered_ids={"n2"}, newly_triggered=[new])
    assert [n.id for n in all_triggered] == ["n2", "n1"]


def test_select_all_triggered_excludes_notes_that_have_never_triggered():
    notes = [_keyword_note(), _path_note()]
    all_triggered = select_all_triggered(notes, already_triggered_ids={"n1"}, newly_triggered=[])
    assert [n.id for n in all_triggered] == ["n1"]


def test_select_all_triggered_preserves_given_order_not_trigger_order():
    notes = [_path_note(), _keyword_note()]
    all_triggered = select_all_triggered(
        notes, already_triggered_ids=set(), newly_triggered=[notes[1], notes[0]]  # triggered n1 then n2
    )
    assert [n.id for n in all_triggered] == ["n2", "n1"]  # still notes' own given order


def test_select_all_triggered_empty_when_nothing_has_ever_triggered():
    notes = [_keyword_note(), _path_note()]
    all_triggered = select_all_triggered(notes, already_triggered_ids=set(), newly_triggered=[])
    assert all_triggered == []
