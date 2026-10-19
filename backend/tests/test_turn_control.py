"""Stop a running turn: finding the loop's task from outside, and cancelling it (no database, no agent_loop import)."""
import asyncio
import importlib.util
import os
import tempfile
import textwrap

from app.services import turn_control


def _fake_agent_loop_module():
    """A module whose file path ends in services/agent_loop.py and which has `async def _run(session_id, user_id)` — the shape
    turn_control looks for — without importing the real agent loop (which needs a database)."""
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "services"))
    path = os.path.join(root, "services", "agent_loop.py")
    with open(path, "w") as f:
        f.write(textwrap.dedent(
            """
            import asyncio

            class Probe:
                cancelled = False

            async def _run(session_id, user_id):
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    Probe.cancelled = True
                    raise

            async def _other(session_id, user_id):
                await asyncio.sleep(30)
            """
        ))
    spec = importlib.util.spec_from_file_location("fake_agent_loop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_finds_the_turn_task_of_the_right_session_only():
    async def main():
        fake = _fake_agent_loop_module()
        a = asyncio.create_task(fake._run("session-a", "u"))
        b = asyncio.create_task(fake._run("session-b", "u"))
        decoy = asyncio.create_task(fake._other("session-a", "u"))  # right argument, wrong coroutine
        await asyncio.sleep(0)
        try:
            assert turn_control.find_turn_task("session-a") is a
            assert turn_control.find_turn_task("session-b") is b
            assert turn_control.find_turn_task("session-c") is None
        finally:
            for t in (a, b, decoy):
                t.cancel()
            await asyncio.gather(a, b, decoy, return_exceptions=True)

    asyncio.run(main())


def test_a_finished_task_is_not_found():
    async def main():
        fake = _fake_agent_loop_module()
        task = asyncio.create_task(fake._run("s", "u"))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert turn_control.find_turn_task("s") is None

    asyncio.run(main())


def test_a_coroutine_from_some_other_file_with_the_same_name_is_ignored():
    async def _run(session_id, user_id):  # defined in this test file, not services/agent_loop.py
        await asyncio.sleep(30)

    async def main():
        task = asyncio.create_task(_run("s", "u"))
        await asyncio.sleep(0)
        try:
            assert turn_control.find_turn_task("s") is None
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(main())


def test_cancel_and_wait_really_stops_the_turn_and_lets_it_clean_up():
    async def main():
        fake = _fake_agent_loop_module()
        task = asyncio.create_task(fake._run("s", "u"))
        await asyncio.sleep(0)
        assert await turn_control.cancel_and_wait(task) is True
        assert task.cancelled() and fake.Probe.cancelled is True

    asyncio.run(main())


def test_cancel_and_wait_reports_a_turn_that_refuses_to_stop():
    async def main():
        release = asyncio.Event()

        async def stubborn():
            while not release.is_set():
                try:
                    await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    pass  # ignores the cancel

        task = asyncio.create_task(stubborn())
        await asyncio.sleep(0)
        assert await turn_control.cancel_and_wait(task, timeout=0.1) is False
        release.set()  # let it end so the test leaves nothing running
        await task

    asyncio.run(main())


def _turn_module_that_reports_its_session():
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "services"))
    path = os.path.join(root, "services", "agent_loop.py")
    with open(path, "w") as f:
        f.write(textwrap.dedent(
            """
            import asyncio
            from app.services import turn_control

            async def _lane():
                return turn_control.session_of_current_turn()

            async def _run(session_id, user_id):
                directly = turn_control.session_of_current_turn()
                in_child_task = await asyncio.gather(_lane())  # a child task, like one lane of a parallel tool batch
                return directly, in_child_task[0]
            """
        ))
    spec = importlib.util.spec_from_file_location("fake_turn_reporter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_call_inside_a_turn_knows_its_session_and_a_call_outside_one_does_not():
    async def main():
        fake = _turn_module_that_reports_its_session()
        assert turn_control.session_of_current_turn() is None  # this test's own task is not a turn
        directly, in_child = await asyncio.create_task(fake._run("session-9", "u"))
        assert directly == "session-9"
        assert in_child is None  # a child task of the turn is not the turn itself

    asyncio.run(main())


def test_the_real_agent_loop_still_has_the_shape_stop_depends_on():
    """If agent_loop's turn coroutine is renamed or loses its session_id argument, Stop silently finds nothing. This pins it.
    Reads the source text so it needs no database."""
    here = os.path.dirname(os.path.abspath(__file__))
    source = open(os.path.join(here, "..", "app", "services", "agent_loop.py"), encoding="utf-8").read()
    assert "async def _run(session_id: str, user_id: str) -> None:" in source
    assert "asyncio.create_task(_run(session_id, user_id))" in source
