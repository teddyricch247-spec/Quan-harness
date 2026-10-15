"""§23.4: 'Capped at 10, rolling (FIFO). Once an 11th checkpoint is created for a
project, the oldest is dropped.'"""
from app.services.checkpoint_fifo import FIFO_CAP, select_ids_to_evict


def test_under_cap_evicts_nothing():
    ids = [f"cp-{i}" for i in range(5)]
    assert select_ids_to_evict(ids) == []


def test_exactly_at_cap_evicts_nothing():
    ids = [f"cp-{i}" for i in range(FIFO_CAP)]
    assert select_ids_to_evict(ids) == []


def test_one_over_cap_evicts_oldest_one():
    ids = [f"cp-{i}" for i in range(FIFO_CAP + 1)]
    assert select_ids_to_evict(ids) == ["cp-0"]


def test_several_over_cap_evicts_that_many_oldest():
    ids = [f"cp-{i}" for i in range(FIFO_CAP + 3)]
    assert select_ids_to_evict(ids) == ["cp-0", "cp-1", "cp-2"]


def test_evicted_ids_are_the_oldest_prefix_in_input_order():
    # list_for_project_ids_oldest_first() is documented to return
    # created_at-ascending order, so eviction must take a prefix, not just
    # "any 3 items" — order matters for correctness here.
    ids = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"]
    assert select_ids_to_evict(ids) == ["a"]


def test_empty_list_evicts_nothing():
    assert select_ids_to_evict([]) == []


def test_custom_cap_respected():
    ids = [f"cp-{i}" for i in range(5)]
    assert select_ids_to_evict(ids, cap=3) == ["cp-0", "cp-1"]
