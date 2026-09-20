"""§23.4: 'Capped at 10, rolling (FIFO). Once an 11th checkpoint is created for a
project, the oldest is dropped.' Extracted to a pure module so it's unit
testable without a database. app/services/checkpoints.py imports FIFO_CAP and
select_ids_to_evict from here."""

FIFO_CAP = 10


def select_ids_to_evict(ids_oldest_first: list[str], cap: int = FIFO_CAP) -> list[str]:
    """`ids_oldest_first` is expected sorted by created_at ascending
    (repositories/checkpoints.py's list_for_project_ids_oldest_first already
    returns it that way)."""
    overflow = len(ids_oldest_first) - cap
    if overflow <= 0:
        return []
    return ids_oldest_first[:overflow]
