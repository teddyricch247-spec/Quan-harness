"""
§20 — Memory System: the I/O shell around memory.py's pure prompt-building.

Called from exactly one place — agent_loop.py's `_finish_turn`, itself called
from exactly the three places a turn genuinely ends in `completed` or
`stuck` (never from a `failed` exit; never from `waiting_approval`, which
isn't a turn ending at all). §20 is explicit that memory is written "never
by the agent directly (it has no memory-writing tool; its system prompt
says so explicitly), always by a backend extraction step" — this module is
that step, and nothing else in this codebase calls it or writes to
project_memory/build_user_memory.

Three independent pieces of work, run concurrently (§20: "a parallel,
smaller call" for the account-level piece — read literally, not just
"in addition to"):
  1. Append the turn's final report, verbatim, to project_memory_log. No
     LLM call.
  2. Revise project_memory.memory_md through the project's own already-
     resolved LLM credential (the same `credential` the turn loop itself
     just used — §20 says "the project's own resolved LLM credential,"
     which is exactly what agent_loop.py already resolved once at the top
     of this turn loop; re-resolving here would just fetch the same thing
     again).
  3. The smaller, parallel account-level check against build_user_memory.
     Explicitly allowed to leave the memory unchanged — see memory.py's own
     BUILD_USER_MEMORY_INSTRUCTIONS.

Best-effort throughout, matching _run_compaction's own reasoning in
agent_loop.py ("compaction is an optimization, not correctness-critical —
skip this round, try again next round"): a failed extraction call must
never turn an already-completed-or-stuck turn into a failed one, and must
never delay the SSE "done" broadcast the person is waiting on — agent_loop.
py's own `_finish_turn` broadcasts done *before* calling this, specifically
so a slow or failing extraction call is invisible to the person's own view
of their session. Every one of the three pieces above catches and swallows
its own exceptions rather than letting one failure take down the other two
(asyncio.gather with each already self-contained, not
return_exceptions=True on a single shared call — a bug in step 2 must not
skip step 1, which needs nothing step 2 does to succeed).

The one thing this deliberately does NOT do: retry. §16.3's three-attempt
exponential backoff already lives inside llm_client.call_llm itself, so a
transient failure is already retried before LlmCallFailedError ever reaches
this module; a further retry here would just be re-running the same
already-exhausted retry policy on top of itself.
"""
import asyncio

from app.repositories import build_user_memory as build_user_memory_repo
from app.repositories import project_memory as project_memory_repo
from app.services import llm_client, memory


async def _append_raw_log(project_id: str, session_id: str, turn_report: str) -> None:
    try:
        await project_memory_repo.append_log(project_id, session_id, turn_report)
    except Exception:  # noqa: BLE001 — see module docstring: best-effort, must not affect the other two pieces
        pass


async def _revise_project_memory(project_id: str, turn_report: str, credential: llm_client.ResolvedCredential) -> None:
    try:
        current = await project_memory_repo.get_memory_md(project_id)
        prompt = memory.build_project_memory_revision_prompt(current, turn_report)
        response = await llm_client.call_llm([{"role": "user", "content": prompt}], tools=[], credential=credential)
        revised = memory.enforce_char_budget(response.text.strip())
        if revised and revised != current:
            await project_memory_repo.set_memory_md(project_id, revised)
    except llm_client.LlmCallFailedError:
        pass  # skip this round's revision — try again after the next completed/stuck turn
    except Exception:  # noqa: BLE001
        pass


async def _revise_user_memory(user_id: str, turn_report: str, credential: llm_client.ResolvedCredential) -> None:
    try:
        current = await build_user_memory_repo.get_memory_md(user_id)
        prompt = memory.build_user_memory_revision_prompt(current, turn_report)
        response = await llm_client.call_llm([{"role": "user", "content": prompt}], tools=[], credential=credential)
        revised = memory.enforce_char_budget(response.text.strip())
        if revised and revised != current:
            await build_user_memory_repo.set_memory_md(user_id, revised)
    except llm_client.LlmCallFailedError:
        pass
    except Exception:  # noqa: BLE001
        pass


async def extract_after_turn(
    project: dict,
    user_id: str,
    session_id: str,
    turn_report: str,
    credential: llm_client.ResolvedCredential,
) -> None:
    """`project` — the same dict agent_loop.py already fetched via
    projects_repo.get_by_id for this turn. `turn_report` — the turn's own
    final report text (agent_loop.py's `_finish_turn` supplies this: the
    final agent message for a completed turn, the stuck explanation for a
    stuck one)."""
    await asyncio.gather(
        _append_raw_log(project["id"], session_id, turn_report),
        _revise_project_memory(project["id"], turn_report, credential),
        _revise_user_memory(user_id, turn_report, credential),
    )
