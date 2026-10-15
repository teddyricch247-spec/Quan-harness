# Phase 3 notes — Turn loop, system prompt, compaction, stuck detection

Written the same way `/docs/PHASE1_NOTES.md` and `/docs/PHASE2_NOTES.md`
were: an honest account of what's real, what's a documented rough edge, and
every place this build had to make a call the spec excerpt didn't fully pin
down. Read this before touching any of Phase 3's code, and before starting
Phase 4.

**The patch.** `phase-3-loop-prompt.md` §18 was patched before any of this was
built, per the separate patch document: the "a connector is just MCP"
sentence added to `PLATFORM_CAPABILITIES`, and the new `COMMUNICATION_STYLE`
block inserted between `AUTONOMY_AND_CAPABILITY_BOUNDARY` and `SECURITY`.
Both edits are what `system_prompt.py`'s static blocks are built from —
extracted programmatically from the patched file, not retyped by hand, so
there's no transcription drift from the source.

## What's real and working

- **Every pure decision module has real, run, passing tests** — same
  pure-core/imperative-shell split Phase 2 established, extended to
  everything this phase adds:
  - `stuck_detector.py` — all four §19 hard-stop signals plus the soft
    warning, each independently triggerable and independently non-triggering.
  - `tool_partition.py` — the read-only/mutating split (§16.2).
  - `compaction.py` / `token_estimate.py` — the 70%-of-context-window trigger
    (§17.1), the checkpoint instruction and re-injection template.
  - `repo_map.py` — ranking/budgeting (§17), and the parser for its own
    single-round-trip scan script.
  - `system_prompt.py` — assembly of all 11 static §18 blocks (including the
    patch) plus the dynamic sections, and their "only if non-empty" rules.
  - `tool_schemas.py` — native tool JSON schemas (view_file, str_replace,
    create_file, execute_bash, run_lint, run_tests, update_plan) and the
    §9.4 runtime MCP tool-schema merge, including Off/Ask/Auto resolution
    and server-name-collision disambiguation.
  - `message_builder.py` — reconstructing a litellm/OpenAI-format message
    list from the `session_events` log, including the interleaved
    call/result grouping described below.
  - `crash_recovery.py` — §16.4's dangling-event classification.
- **`agent_loop.py`** — the actual turn loop: context assembly every
  iteration, `call_llm` with retry, read-only/mutating partitioning and
  execution, Ask-gate creation and resumption, compaction, the stuck
  detector wired in after every mutating call, the iteration ceiling, and
  the crash-recovery scan run on every session resume (not only after a
  literal restart — see below).
- **`llm_client.py`** — credential resolution (project's own, falling back
  to the account default), a litellm-based `call_llm` with three-attempt
  exponential backoff (§16.3), and `get_context_window` via
  `litellm.get_model_info` with a conservative fallback.
- **`mcp_tools.py`** — the runtime `tools/call` counterpart to Phase 2's
  handshake-only `mcp_handshake.py`, reusing its transport helpers rather
  than forking them.
- **Two real Phase 2 fixes, made because this phase needed them to be
  correct, not as drive-by cleanup:**
  1. `mcp_handshake.py` was discarding each discovered tool's `inputSchema`
     and read-only annotation, keeping only `name`/`description` — fine when
     nothing called a connector tool (Phase 2 had no turn loop), but §9.4's
     runtime merge needs the real schema to hand the model. Now captures
     both, defaulting a missing schema to an open object and a missing
     annotation to "not read-only" (the conservative default).
  2. `shell_tools.execute_bash`'s audit rows were hardcoded to
     `initiated_by="system"`, with a comment in `audit.py` explicitly naming
     this as a placeholder until Phase 3's turn loop became the real caller.
     Now `"agent"`. Also gained a `bypass_guard` parameter — the only way an
     approved, previously-guard-blocked command can actually re-run without
     immediately re-tripping the same rule on the same unchanged text.
- **New repositories**: `session_events.py` (the append-only turn-loop log —
  everything else in this phase reads from it rather than holding state
  anywhere else), `approval_requests.py`. `sessions.py` gained
  `update_fields`, an internal/unscoped helper for the loop's own frequent
  status/plan/iteration-count writes.
- **The agent-facing HTTP surface** (`app/routers/agent.py`) Phase 1's own
  `sessions.py` docstring named as deferred: `POST /messages`,
  `POST /interrupt`, `GET /events`, `GET /stream` (SSE), and
  `POST /approvals/{id}/resolve`.

## Testing — what actually ran, and what needs real infrastructure

This sandbox had **no network and no package installs available**, the same
constraint Phase 2 documented — but this phase hit it harder: even
`fastapi`/`pydantic-settings`/`httpx`/`supabase`/`litellm` themselves aren't
installed here (Phase 1/2's own environment apparently had them; this one
didn't), so nothing that imports the FastAPI app, a repository, or the LLM
client can actually run, even in isolation.

**Ran for real, 116/116 passing**, via a small manual assert-based runner
(no `pytest` binary either) — `test_stuck_detector.py` (23),
`test_tool_partition.py` (9), `test_compaction.py` (10), `test_repo_map.py`
(14), `test_system_prompt.py` (13), `test_tool_schemas.py` (14),
`test_crash_recovery.py` (11), `test_message_builder.py` (22, including the
interleaved-grouping and condensation-boundary cases below). These are the
graded, load-bearing decision modules — kept dependency-free specifically so
this was possible at all, same reasoning Phase 2 gave for `guard_rules.py`
and `checkpoint_fifo.py`.

**Logic validated, not run as the shipped test** — `llm_client.py`'s pure
helpers (`_litellm_model_string`, `_to_function_tools`, `_normalize_response`)
were checked against an isolated copy of the same code, since
`app.services.llm_client` can't even be imported here (its module-level
`from app.repositories import llm_credentials` chain reaches `pydantic_settings`
before anything pure-logic is touched). `tests/test_llm_client.py` (8 tests)
is written normally, importing the real module, for when this runs somewhere
with `requirements-dev.txt` actually installed — bringing the total written
this phase to 124.

**Reviewed, not run at all** — `agent_loop.py`, `mcp_tools.py`,
`routers/agent.py`, and the two repositories. No database, no workspace, no
LLM credential, no MCP server were reachable here. These were read through
multiple times end-to-end by hand rather than exercised, and **several real
bugs were caught this way, before shipping**:
- `message_builder.py`'s tool-call grouping originally required a step's
  `tool_call` events to be *contiguous* in the log — but `agent_loop.py`
  appends each mutating call's result immediately after executing it (for
  live SSE streaming), which interleaves `tool_call`/`tool_result` events.
  Fixed by making the grouping scan tolerate interleaved results belonging
  to already-collected calls; `test_interleaved_call_result_call_result_*`
  and `test_an_unrelated_event_between_calls_breaks_the_group` cover it.
- Compaction's `condensation_summary` event is necessarily appended
  *after* the events it needs to logically precede (it's created by an
  auxiliary call that runs partway through the session, summarizing
  everything before it — but gets a later, not earlier, event id). Fixed by
  giving it a `kept_from_event_id` field and a dedicated pure function,
  `message_builder.apply_condensation`, that reassembles \[summary, kept
  events...\] in the right logical order regardless of storage order —
  tested directly (`test_apply_condensation_*`).
- `update_plan` had no execution dispatch at all in an early draft — it was
  in the tool schema and in the stuck-detector's tool-name set, but nothing
  actually wrote `sessions.plan`. Caught on a re-read of `_execute_native`.
- §14.10's actual plan-step schema uses `"step"`/`"done"`, not the
  `"content"`/`"completed"` names an early draft of `system_prompt.py`
  assumed — caught by re-reading the patched spec's own JSON block rather
  than by a test (a wrong-but-internally-consistent field name wouldn't have
  failed any test that didn't independently know the real schema).
- A hallucinated or since-revoked `mcp__...` tool name, resolved to "Ask" by
  `_resolve_permission_for_call`'s cautious default, would have created a
  real `approval_requests` row for a tool that could never actually execute
  — pausing the whole session for a human to reject something meaningless.
  Fixed to check tool existence before creating the approval row and fail
  the call cleanly instead.

**Update, pre-Phase-4 cleanup (see that section below).** `agent_loop.py`'s tool
dispatch (`_execute_call`) and its approval-resume path
(`_action_resolved_approval`) are now under test —
`tests/test_agent_loop_audit.py`, 16 tests, every collaborator replaced by an
in-memory double. That is the first test coverage `agent_loop.py` has had, and
it covers *only* those two functions: `_run_inner`'s turn loop itself (the LLM
call, Ask-gating, stuck detection, SSE, crash-recovery scan, compaction
trigger) is still exercised by nothing but reading it. With the current
additions the pure-module suite is 264 tests, all passing under the same
manual runner described above; `pytest` itself still hasn't been run against
this codebase in any environment used to build it — run it for real
(`pip install -r requirements-dev.txt && pytest`) as the first thing in a
machine that has network access, before anything else in this list.

**Run these against real infrastructure before trusting this in
production** — a live Supabase project, a live Fly.io workspace, and at
least one real LLM credential per provider `_litellm_model_string` maps
(Anthropic/OpenAI/Google/OpenRouter/a custom OpenAI-compatible endpoint).

## Post-build audit — real bugs found and fixed

A second, dedicated pass through this phase's own code after it first shipped
— re-reading every cross-module call against its actual definition rather
than against memory, since most of this was never actually run. Found and
fixed nine real issues; none needed a test-suite change beyond what's noted
below (all 116 tests still pass after every fix).

1. **SSE catch-up race** (`routers/agent.py`). `agent_loop.subscribe()` was
   called *after* fetching the catch-up history — an event appended in the
   gap between the fetch and the subscribe call would land in neither the
   history burst nor the live queue, and simply never reach the client.
   Fixed by subscribing first and de-duplicating anything the live queue
   delivers that's already covered by the catch-up burst
   (`last_history_id`), with an explicit unsubscribe on the not-found path
   so a failed lookup doesn't leak a queue entry.
2. **Uncaught `ValueError` from `resolve_repo_path`** (`file_tools.py` —
   pre-existing Phase 2 code, but this phase is its first live caller). A
   path outside the repo root, an absolute path, or an empty path raises
   `ValueError` from `resolve_repo_path`, and none of `view_file`,
   `str_replace`, or `create_file` caught it — Phase 2 never had a caller
   that could hand these a live, untrusted, model-supplied path, only tests
   with well-formed ones. Confirmed by hand that this is genuinely reachable
   (`../../etc/passwd` and similar), then fixed all three the same way
   `str_replace` already handled `StrReplaceMatchError`: catch, return
   `ToolResult(ok=False, error=...)`. `create_file` was the most exposed —
   no "must be viewed first" gate ahead of it the way `str_replace` has.
   `resolve_repo_path` itself is untouched; existing Phase 2 tests that call
   it directly are unaffected (verified by hand — `pytest` itself isn't
   installed in this sandbox, so its own test file couldn't be run, only
   its assertions re-checked manually against the unmodified function).
3. **A real TOCTOU race in `start_turn`/`send_interrupt`/
   `resume_after_approval`.** Each checked `agent_loop.is_running(session_id)`
   and then, several `await`s later, called `_spawn()` — a real gap where two
   near-simultaneous requests for the same session (a double-click, a client
   retry) could both see "not running" and both end up spawning a turn loop.
   Fixed with an atomic claim (`_claim_session`, called with no `await`
   between the check and the set — Python's cooperative scheduler can't
   interleave two coroutines except at an `await` point, so this pair can't
   race) and a matching `_release_session` on every path that claims but
   then decides not to spawn, including on an exception raised in between —
   caught, on the first pass, missing exactly the plain (non-exception)
   early-return path in `start_turn`, which would otherwise have left that
   session's claim permanently stuck with no task ever actually running to
   release it. Fixed on a second look at the same function.
4. **An approved, previously-guard-blocked `execute_bash` call lost its
   originally-requested `timeout_seconds`** on re-run — the approval payload
   only ever stored `command`, so the retry silently fell back to the 120s
   default regardless of what the model actually asked for. Now preserved
   in the payload and passed through on approval.
5. **No defense against a non-integer `timeout_seconds` or malformed
   `view_range`** coming back from the model's own JSON tool call —
   `shell_tools.execute_bash`'s `min(max(timeout_seconds, 1), ...)` would
   raise `TypeError` on a string, crashing the whole turn rather than
   reporting a normal tool failure. Added `_safe_int` and made `_as_range`
   defensive the same way.
6. Unused import (`projects_repo` in `llm_client.py`), dead code
   (`tool_schemas.py`'s `seen_slugs`, which was tracked but never actually
   read; `_to_stuck_event`'s `read_only` parameter, threaded through every
   call site but never used inside the function — `StuckEvent` doesn't need
   it, and stuck_detector.py's own signals don't distinguish read-only from
   mutating calls).
7. Three stale/misleading docstrings, all now describing a Phase 3 that
   hadn't landed yet when they were written: `sessions.py` still said "there
   is no turn loop yet (Phase 3)"; `workspace.py` still said these tools have
   "no caller at all until Phase 3's turn loop exists"; `checkpoints.py` was
   the most actually-misleading one, phrased as though Phase 3 would
   populate `conversation_snapshot` for real — when Phase 3 landed and
   deliberately decided not to (rough edge #7 below). All three corrected to
   describe what's actually true now.
8. **A real improvement, not just a fix**: compaction's token-count check
   was estimating from re-stringified `session_events` content (dict
   `repr()`, including field names like `"role"`/`"ok"` that were never part
   of any real message) rather than using the actual token count the
   provider already reports. `llm_client.LlmResponse.input_tokens` was sitting
   right there, unused, after every real call_llm. Now the loop tracks the
   most recent real count and uses it for the *next* iteration's compaction
   check, falling back to the crude estimate only for the very first call of
   a turn (before any real number exists) or for a provider that never
   reports usage.

## Post-handoff patch — four gaps closed before Phase 4

This phase's initial self-review (the "Post-build audit" section above) was
run before handoff. A second, independent review after handoff — done by
someone who hadn't written this code — caught one gap that audit missed
entirely, plus three rough edges below (#1, #7, and the caching split noted
under "What Phase 4 needs to know") worth closing now rather than carrying
into Phase 4. All four are patched; kept here rather than deleted so the
record of what was wrong and why survives.

1. **`audit_log` never got a row for anything but `execute_bash`, checkpoint
   restore, and push/pull — not caught by this phase's own review.** §27
   is explicit: "the complete record of everything that happened, across
   every tool, regardless of outcome." `str_replace`, `create_file`,
   `view_file`, `run_lint`, `run_tests`, `update_plan`, and every `mcp__`
   connector call executed with zero `audit_repo.record` call anywhere in
   the path, success or failure. Fixed by instrumenting `agent_loop.py`'s
   `_execute_call` — the one chokepoint both the normal turn loop and
   §16.4's crash-recovery re-execution already funnel every real tool call
   through — rather than threading an `audit_repo.record` call into each of
   the six-plus individual tool branches separately. `execute_bash` is
   deliberately excluded from this new wrapper (it already audits itself
   inside `shell_tools.py`, guard-blocked case included, before
   `_execute_call` even sees an outcome); double-instrumenting it would have
   written two rows for one call. The one other path that calls a tool
   outside `_execute_call` — `_action_resolved_approval`'s connector-tool
   branch, resolving an already-approved Ask-gated call — got its own
   explicit `audit_repo.record` call for the same reason. A lean
   `input_payload` (never a file's full before/after content — that's
   already in `session_events` verbatim, this would just be duplicating it)
   and an `output_summary` only on failure, both matching the shape
   `shell_tools.execute_bash`'s own existing audit call already used.
2. **`checkpoints.create_checkpoint`'s `conversation_snapshot` parameter is
   now actually populated**, closing rough edge #7. `agent_loop.py` passes
   its own current-iteration `events` list — the same list it just built
   that iteration's `messages` from — through `file_tools.str_replace`/
   `create_file` and `shell_tools.execute_bash` into `create_checkpoint`.
   All three signatures grew the new parameter at the end, defaulting to
   `None`, so every existing Phase 1/2 call site and test is unaffected.
3. **§17's static/dynamic prompt-caching split is now honored for the
   Anthropic provider.** `system_prompt.py` gained `assemble_static()` (the
   existing `assemble()` refactored to use it, output unchanged); `llm_client
   .call_llm` now runs every outgoing message list through a new
   `_apply_prompt_caching`, which — only when `credential.provider ==
   "anthropic"`, and only when the system message is in exactly the shape
   `message_builder.build_messages` actually produces — splits the system
   message into two content blocks and marks the static one with
   `cache_control: {"type": "ephemeral"}`. Deliberately not attempted for
   the other four providers: OpenAI already caches a repeated prefix
   automatically with no marker needed; Gemini's prompt caching is a
   materially different explicit cache-object API, not a per-request flag;
   and what OpenRouter or a custom endpoint does with an unrecognized
   `cache_control` key is unverified against a real endpoint (this whole
   module was written with no network access — see rough edge #4/#10
   below). Fails open by design — any unexpected shape (wrong role,
   non-string content, content that doesn't start with the current static
   prefix) returns `messages` unchanged rather than raising, since a missed
   cache breakpoint should never be why a turn fails.
4. **The repo map's adjacency graph is now actually built**, closing rough
   edge #1. `SCAN_SCRIPT` gained two more grep passes — Python
   `import`/`from` lines, JS/TS relative `import`/`require` lines — and a
   new pure function, `build_adjacency`, resolves each one against the same
   file listing the scan already produced (dotted Python modules mapped to
   `a/b/c.py` or `a/b/c/__init__.py`; relative JS/TS specifiers resolved
   against the importing file's own directory, trying each real extension
   and an `index.*`). Anything that doesn't resolve to a real file in this
   scan — a third-party package, a bare specifier, a Python relative
   `from . import x` (not attempted — see `_resolve_python_import`'s
   docstring for why), a dynamic `require(x)` — is silently dropped, never
   guessed at. `build_repo_map` now calls this and passes the result into
   `rank_and_budget`'s existing (and already-tested) `adjacency` parameter,
   which needed no changes at all. Adding the two new markers to
   `SCAN_SCRIPT` required updating `parse_scan_output`'s own section
   splitter too — without that, lines under the new markers would have
   fallen through into the JS/TS signature section right before them and
   been parsed as bogus signatures; `_split_sections` is now the one shared
   splitter both `parse_scan_output` and `build_adjacency` use, so they
   can't disagree about where a section ends. Verified against real `bash`
   execution of the actual `SCAN_SCRIPT` string against files on disk, not
   just hand-built fixture strings — see `test_repo_map.py`'s new
   `build_adjacency` test section for the fixture-based coverage that
   shipped with this.

None of these four were exercised against real infrastructure — same
caveat as everything else in this document; see "Testing" above and rough
edges #4/#10 below, still open.

## Pre-Phase-4 cleanup — audit labels, import graph, scan hygiene

The "Post-handoff patch" above was itself reviewed — including against a second,
independently produced fix of the same four findings — and that comparison
turned up defects in it, closed here before Phase 4 starts building on top.

1. **`audit_log` rows used a different vocabulary than the schema and than
   `execute_bash`'s own rows.** `_execute_call` wrote `tool=<raw tool name>,
   action='tool_call'`, while `0005_sessions.sql`'s own column comment documents
   `tool` as a *category* (`'bash' | 'file_edit' | 'mcp:<server_name>' | …`) and
   `shell_tools.execute_bash` already wrote `tool='bash', action='execute_bash'`
   — two conventions in one table, so a filter on any one category would have
   missed rows. Every writer now uses `tool` = category, `action` = the specific
   tool name within it:

   | tool call | `tool` | `action` |
   |---|---|---|
   | `view_file`, `str_replace`, `create_file` | `file_edit` | the tool name |
   | `run_lint`, `run_tests` | `bash` | the tool name |
   | `execute_bash` (unchanged — audits itself) | `bash` | `execute_bash` |
   | `update_plan` | `plan` | `update_plan` |
   | a connector tool | `mcp:<server_name>` | the connector's own tool name |
   | a connector tool no longer granted to the project | `mcp:unavailable` | the model-facing name |
   | a tool name nothing recognizes | `unknown` | the name as sent |

   `plan`, `unknown` and `mcp:unavailable` are additions to the vocabulary; 0005's
   comment was updated to list them (**comment-only — no schema change, nothing to
   re-run**). Both places that write an agent audit row (`_execute_call` and
   `_action_resolved_approval`'s connector branch) now go through one helper,
   `_record_tool_audit`, so they can't drift apart again. The payload hygiene the
   patch introduced is unchanged and now covered by tests: a file's
   `old_str`/`new_str`/`file_text` never reaches the table (it's already verbatim in
   `session_events`), and a connector call records argument *names* only — the
   comparison fix persisted full arguments, which put ~100 KB in one `str_replace`
   row and a connector `api_key` value into the table verbatim.
   `tests/test_agent_loop_audit.py` (16 tests) covers the labels, the payloads,
   the no-double-row rule for `execute_bash`, failure/truncation, and both call
   sites. Checked by mutation, not just by passing: sending raw arguments to the
   table fails 3 of them; reverting the labels fails 5.
2. **The repo map's import graph resolved almost nothing on Quan's own layout.**
   Run against this repository itself (131 files, as it stood before this
   cleanup), `build_adjacency` found **1 edge**: Python imports were resolved only against the repo root, but the
   backend is `backend/app/...` imported as `app....`; and JS/TS resolution was
   relative-only, but 67 of the frontend's ~110 import specifiers use the `@/`
   alias. Fixed in `repo_map.py`:
   - *Python:* a dotted module (`app.services.x`) is tried against every ancestor
     directory of the importing file, deepest first — a source root is in practice
     always one of them. A **single-word** module (`import logging`, `import
     config`) is deliberately held to the importing file's own directory and the
     repo root only, because a bare name overwhelmingly means the stdlib or a
     third-party package and would otherwise attach to an unrelated
     `backend/app/logging.py`.
   - *JS/TS aliases:* read from the nearest `tsconfig.json`/`jsconfig.json` above
     the importing file (its `paths`, joined onto its `baseUrl` or its own
     directory) via a new `@@TSCONFIG@@` section in `SCAN_SCRIPT`, not hardcoded
     to `@/`. The nearest config wins outright; a file with no config above it
     gets no alias resolution at all rather than a guess.
   - *Re-exports:* the JS/TS import grep is now `^(import|export).*from |require\(`
     (was `^import |require\(`), so `export * from './api'` counts as an edge.
   Verified against ground truth computed independently of `repo_map.py` — an
   `ast` parse of every Python file and a JSON read of the real tsconfig — on this
   repository as shipped (132 files): **254 edges found, 0 false positives.**
   Recall: Python 186 of 223 real edges, TS/TSX 68 of 69. Every miss was classified and is a limitation
   already documented: 27 multi-line parenthesized `from x import (\n a,\n b\n)`
   (the largest remaining gap), 10 function-level (indented) imports, and 1
   side-effect `import "./globals.css"`. `test_repo_map.py` grew from 22 to 40
   tests, including two that execute the real `SCAN_SCRIPT` under `bash` against
   a temp directory; 11 of the new ones fail against the previous implementation.
3. **The scan descended into `node_modules` (found while adding the tsconfig
   pass).** `SCAN_SCRIPT`'s `find` excluded only `.git` and `.qh-scratch-home`, and
   its `grep -r` passes excluded nothing, so any workspace where the agent had run
   `npm install` — which SECURITY explicitly allows — would have put every
   installed package into the repo map's file listing (blowing past §17's
   150-file "small repo" threshold and burying real files under path-only noise),
   and would have made every grep pass crawl them; the new tsconfig pass would
   additionally have picked up every package's own `tsconfig.json`. The listing
   and every grep now exclude `.git`, `.qh-scratch-home`, `node_modules`, `.next`,
   `__pycache__` and `.venv` (`find` prunes by name, so it never walks them).
   Behavior change to be aware of: the file count that gates §17's ranking
   threshold no longer includes any of those directories.

**Deliberately not changed here — still open going into Phase 4:**

- **Memory will land in the uncached half of the system prompt.** §17 groups user
  and project memory with the *static* portion, but `system_prompt.py` (§18's own
  section order) renders `WHAT_YOU_KNOW_ABOUT_*` inside the dynamic tail, after
  `REPO_CONTEXT`, and only the 11 static §18 blocks get a `cache_control`
  breakpoint. Phase 4.1 works as-is — it just gets no caching discount on memory
  text. Fixing that is a real trade-off, not a bug: either accept it, or give
  memory its own breakpoint, which means rendering it *before* `REPO_CONTEXT`
  (which changes every step and would otherwise sit between the two and defeat the
  cache) and so departs from §18's listed order. Decide this deliberately while
  building 4.1.
- **`_run_inner` and everything around it is still untested** — see the Testing
  section. A smoke run against a throwaway repository with real Supabase, LLM and
  workspace credentials should happen before 4.1 builds on the loop.
- **Import-graph gaps that remain:** multi-line parenthesized Python imports;
  function-level Python imports; Python relative imports (`from . import x`);
  JS/TS side-effect imports and multi-line imports; a tsconfig reached only via
  `extends`; a `paths` entry whose array spans several lines.
- **If a tool call raises** (rather than returning a failed result), no audit row
  is written — the exception reaches the turn loop, which records it as its own
  transcript event. Unchanged from before; noted so it isn't mistaken for
  something the new tests cover.

## Rough edges (same spirit as Phase 1's OAuth section and Phase 2's — flagged, not hidden)

1. **~~The repo map's "lightweight PageRank-style pass over a symbol graph"
   (§17) is, honestly, a one-hop adjacency boost~~ — the graph is now built, and
   resolves real edges; see "Post-handoff patch" and "Pre-Phase-4 cleanup"
   above.** `build_adjacency` builds that one-hop graph from `SCAN_SCRIPT`'s
   import lines and `build_repo_map` passes it through. Still, deliberately, a
   one-hop adjacency boost rather than a real PageRank iteration — §17's own
   language overstates what's practical to build from regex-extracted signatures
   at this file-count scale, and a real iterative PageRank pass wasn't judged
   worth its own complexity for the directionally-identical effect a one-hop
   boost already gets at the "a few hundred files" scale §17's own threshold
   implies. Remaining gaps are listed at the end of "Pre-Phase-4 cleanup".
2. **Same tree-sitter gap Phase 2 already flagged, now also relevant to
   `repo_map.py`'s signature extraction** — regex-based
   (`^(class |def |async def )` for Python; a handful of `export`/`function`/
   `class`/`const` patterns for JS/TS), not a real parse, for the same "not
   verified against a real install in this environment" reason
   `PHASE2_NOTES.md` gives for `text_edit.py`'s syntax check. The two call
   sites should share one real parser if `tree-sitter` is ever actually
   installed, rather than gaining two separate heuristics.
3. **No MCP OAuth token refresh.** `mcp_oauth.py` has `exchange_code` but no
   refresh-token exchange function. `mcp_tools.call_tool` surfaces an
   expired token as a plain failed tool result the model sees and can
   report, rather than silently refreshing and retrying — a real gap for
   any OAuth-authenticated connector whose access token has a short TTL.
4. **`litellm`'s provider → model-string mapping is a real design decision,
   not something §7 spells out**, and untested against a live credential:
   `anthropic`→`anthropic/`, `openai`→`openai/`, `google`→`gemini/`,
   `openrouter`→`openrouter/`, and `custom` treated as an OpenAI-compatible
   HTTP surface reached via `api_base` (the common shape for a self-hosted or
   third-party endpoint). Verify each mapping against a real call before
   relying on it — see `llm_client.py`'s own docstring.
5. **`get_context_window`'s fallback is a hardcoded 128,000 tokens** if
   `litellm.get_model_info` doesn't recognize the model string (a custom
   endpoint's model name, or a model newer than the installed `litellm`
   version knows about). Compaction just triggers a bit earlier than
   strictly necessary in that case — a safe failure mode, but worth knowing
   about if compaction seems to fire earlier than expected against an
   unusual model.
6. **SSE is single-process, in-memory only** (`agent_loop.py`'s
   `_subscribers`/`_running_sessions` module-level dicts). A second backend
   instance, or a restart mid-stream, drops any open SSE connections — the
   client's job is to reconnect with `after_id` set, which the endpoint
   supports, but there's no cross-instance pub/sub. Fine for a single Render
   service; would need Redis or Postgres `LISTEN`/`NOTIFY` to scale beyond
   one instance.
7. **~~`checkpoints.create_checkpoint`'s `conversation_snapshot` parameter is
   still never populated~~ — FIXED, see "Post-handoff patch" above.**
   `agent_loop.py` now threads its current-iteration `events` list through
   `file_tools.py`/`shell_tools.py` into every real checkpoint. A
   checkpoint's git commit sha was always what `restore_checkpoint` actually
   depends on; the conversation snapshot is additional context alongside it,
   not a replacement for it.
8. **"Per-hunk resolution on a multi-file diff"** (implementation order step
   10; `approval_requests.payload`'s own migration comment: "for a
   multi-hunk diff proposed by an MCP merge tool, includes a `hunks`
   array") — no special handling exists for this beyond what's already
   generic: `payload` is exactly the gated call's tool name and arguments,
   whatever shape those happen to be. If a specific MCP tool's arguments are
   ever hunks-shaped, they'd flow through into `payload` unchanged and the
   approve/reject flow works the same as for any other call — but nothing
   here specifically renders or resolves individual hunks, since no concrete
   connector that behaves this way exists to build against yet.
9. **`web_search`, `browser_*`, and `delegate_task`** are described in §18's
   own text (shipped verbatim, per the patch) as capabilities the agent has,
   but have no real tool implementation anywhere in this codebase — Live
   Preview and the headless browser are explicitly Phase 5 per the roadmap;
   web search and sub-task delegation aren't listed as Phase 3 scope either.
   `tool_schemas.py`'s `build_full_tool_list` simply never includes them
   (they're not in `NATIVE_TOOL_SCHEMAS`), so the merged tool list the model
   actually receives is narrower than what the system prompt's own text
   describes. This is a known, spec-acknowledged gap, not an oversight —
   implementation order step 9's own instruction to exercise this "against a
   disposable throwaway repository before connecting anything real" reads as
   anticipating exactly this kind of preliminary mismatch. Left for whichever
   phase actually lands each capability to add its tool schema and fold it
   into the merge, rather than guessed at here.
10. **`litellm==1.55.4` in `requirements.txt` is a version pin chosen without
    being able to verify it resolves** — no network for `pip install` in
    this environment. Confirm it still exists and pulls in a reasonable
    dependency set before deploying.

## Design decisions this phase had to make that the spec excerpt didn't spell out

- **A resumed session (after an approval resolves, or after a crash) is
  treated as "a fresh turn loop" in every sense**, including resetting
  `turn_iteration_count` to 0 — taken literally from §16.2's own line, "a
  fresh turn loop starts from there." The alternative (treating a resume as
  a continuation of the same iteration count) would arguably guard better
  against a pathological "trigger approval after approval to dodge the
  ceiling" pattern, but the spec's wording is explicit enough that this
  didn't seem like a judgment call worth overriding.
- **Two events on approval resolution, not one** — an `approval_response`
  event (role `user`, parent = the `approval_request` event; records the
  person's decision) and a `tool_result` event (parent = the original
  `tool_call` event; records what actually happened as a result — a real
  execution outcome if approved, or a synthesized "Rejected by the user"
  result if not). Reconciles two sentences in §16.2 that read like they
  could be describing the same event ("the resolution is appended with
  parent_event_id pointing at the gated call's approval_request event" vs.
  "\[rejections are\] appended as the tool's result") — they're describing
  two different, both-necessary events.
- **Crash recovery's dangling-event scan runs at the start of every
  `run_turn_loop` call, not only after a detected crash** — because §16.4
  itself frames it as "on any session resume, before taking a new turn,"
  and a resumed-after-approval session is exactly that. There's no separate
  "was this a real crash" signal to check even if one were wanted.
- **A resolved-approval's `approved`/`rejected` status is read from the
  `approval_requests` row itself, not inferred from `crash_recovery.py`'s
  generic event-log scan.** `crash_recovery.find_dangling_events` correctly
  flags an unresolved `approval_request` event as dangling (kind
  `pending_approval`), but has no way to tell "still pending" apart from
  "resolved, but the loop hasn't run since to act on it" — both look
  identical from the event log alone until the loop actually appends the
  follow-up events. `agent_loop.py` handles this with its own check against
  the authoritative DB row instead, and only uses `crash_recovery.py`'s
  output for genuine `tool_call` dangling (`reexecute`/`interrupted`).
- **A call after an Ask-gated one in the same model response is never
  recorded** (no `tool_call` event at all), not recorded-then-abandoned.
  §16.2 says these are "discarded, not queued" — persisting them anyway
  would create an event that can never get a result and that future
  crash-recovery scans would keep re-flagging as dangling, forever, since
  nothing would ever act on it.
- **Read-only calls bypass Auto/Ask/Off entirely, including for MCP
  connector tools** — §16.2's pseudocode states plainly that "read-only
  calls are always Auto," which taken literally means a connector tool
  marked side-effect-free at connection time (`readOnlyHint`) executes
  without ever consulting its own stored `permission_state`, even if that
  happens to be `ask`. This is a real tension with `PLATFORM_CAPABILITIES`'
  more general "follows the same SECURITY rules... based on its Auto/Ask/Off
  state" framing, which doesn't carve out an exception for read-only tools.
  §16.2's explicit, specific statement was treated as authoritative over the
  more general framing elsewhere.
- **`run_lint`, `run_tests`, and `update_plan` default to the mutating
  partition** — none of the three is on §16.2's own read-only allow-list
  (`view_file`, `web_search`, the `browser_*` tools), and none is named
  alongside `str_replace`/`create_file`/`execute_bash` as always-mutating
  either. `run_lint`/`run_tests` run through the same `exec_in_workspace`
  primitive `execute_bash` does, so the same "could race at the filesystem
  level" reasoning applies; `update_plan` has no real race to avoid (it only
  touches this session's own row) but there's no benefit to special-casing a
  single low-frequency call into the concurrent lane either.
- **Native tool JSON schemas were reverse-derived from Phase 1/2's actual,
  already-shipped function signatures** (`file_tools.py`/`shell_tools.py`),
  not from an original §14 schema bundle — no file matching "the Phase 2
  system prompt" exists anywhere in this repository to extract from the way
  §18's blocks were extracted from the (patched) Phase 3 bundle. `update_plan`
  is the one exception, reproduced exactly from §14.10's own given JSON block.
- **MCP connector tools are namespaced as `mcp__{server-name-slug}__{tool-name}`**
  in the model-facing tool list — the same convention already visible
  elsewhere in tool ecosystems that merge multiple MCP servers into one flat
  tool list, picked for exactly that reason (a recognizable, established
  shape) rather than invented from scratch. Server-name collisions get a
  short id-fragment suffix so two identically-named connectors both stay
  distinguishable and callable.

## NOTICES.md

Both remaining placeholder rows are now filled in: OpenHands (§18's system
prompt) and DeepSeek Harness (§17.1's compaction instruction and re-injection
framing) each have a completed entry, matching Aider's from Phase 2. Aider's
own entry also gained an addendum for the repo-map concept (§17), which
landed this phase too — it was originally scoped against the same row but
deferred at the end of Phase 2's own notes.

## What Phase 4 needs to know

- **Memory and Project Knowledge have real extension points already wired,
  currently always empty.** `system_prompt.DynamicSections` has
  `project_knowledge`, `what_you_know_about_this_person`, and
  `what_you_know_about_this_project` fields — all `None` today (each section
  is omitted from the assembled prompt whenever its field is `None`, per
  §18's own "only if..." rules). `agent_loop.py`'s `_run_inner` is where
  these would get populated each iteration (or, for the two memory fields,
  possibly once per session rather than every iteration — see the note
  below on §17's static/dynamic split).
- **§17's static/dynamic prompt-caching split is now honored, for Anthropic
  credentials** — see "Post-handoff patch" above. `llm_client._apply_prompt_
  caching` marks `system_prompt.assemble_static()`'s exact text as a
  provider-side cache breakpoint. What it does *not* do: memoize anything
  in-process, or help at all for OpenAI/Google/OpenRouter/custom credentials
  (OpenAI needs nothing extra; the other three are real follow-up work, not
  attempted here — see that same section for why). If Phase 4's memory
  fields end up large enough that recomputing `render_dynamic_sections`
  every iteration becomes its own cost concern (separate from the
  provider-caching question above), an in-process memoization keyed on
  session id plus a "memory changed" version counter is still the fallback
  approach, still not implemented.
- **The repo map's adjacency graph is built, and resolves real edges on this
  repo's own layout** — see rough edge #1 and "Pre-Phase-4 cleanup" above.
  `build_adjacency` is regex-based and one hop; it resolves Python absolute
  imports against any ancestor directory of the importing file, JS/TS relative
  and `tsconfig`-alias imports, and re-exports, and silently drops anything it
  can't resolve to a real file (third-party packages, Python relative imports,
  multi-line imports, dynamic `require(x)`) rather than guessing. If Phase 4 or
  later work ever installs a real `tree-sitter` parser (see rough edge #2), that
  same parse pass could replace both this and the signature-extraction regexes
  with one real AST walk — not required, just the natural next step if that
  dependency ever lands.
- **`audit_log.tool` is a category, and every writer now follows it** (table in
  "Pre-Phase-4 cleanup" above). Anything Phase 4 adds that writes agent audit
  rows — memory extraction calls, a scheduled run's tool calls, the connector
  review flow — should use that vocabulary (`tool` = category, `action` = the
  specific name), and a new native tool needs an entry in
  `agent_loop._NATIVE_AUDIT_CATEGORY` or it is recorded as `unknown`. A scheduled
  run (§26) uses the same dispatch, so its calls are audited by default.
- **Memory (4.1) will render in the uncached half of the system prompt unless you
  decide otherwise** — see the first "not changed here" item in "Pre-Phase-4
  cleanup". Decide it before writing the memory-injection code, since it affects
  where in `render_dynamic_sections` those fields go.
- **`tool_schemas.NATIVE_TOOL_SCHEMAS` is where `web_search`/`browser_*`/
  `delegate_task` schemas should be added once those capabilities are real**
  (see rough edge #9) — `build_full_tool_list` will pick them up
  automatically once they're in that list; nothing else needs to change.
- **MCP OAuth refresh** (`mcp_oauth.py`) needs a real token-refresh exchange
  function before `mcp_tools.call_tool` can do anything smarter than
  surfacing an expired token as a plain tool failure — see rough edge #3.
- **No frontend chat/streaming UI was built this phase.**
  `frontend/app/projects/[id]/sessions/page.tsx` is still Phase 1's
  create/list placeholder — nothing consumes the new `/messages`,
  `/interrupt`, `/stream`, or `/approvals/{id}/resolve` endpoints yet.
  `phase-3-loop-prompt.md` itself is scoped entirely to the backend
  orchestration loop (its own title: "Turn Loop, System Prompt, Compaction,
  Stuck Detection") with no frontend component mentioned anywhere in it, so
  this was treated as out of this phase's scope rather than an oversight —
  but it's real, necessary follow-up work before an actual person can use
  any of this. `lib/types.ts`'s `Session` interface did get the new `plan`
  field added, to stay in sync with the backend schema for whoever builds
  that UI next.
- **Every new module this phase added follows the same pure-core/imperative-
  shell split** Phase 2 established — `stuck_detector.py`, `tool_partition.py`,
  `compaction.py`, `repo_map.py`, `system_prompt.py`, `tool_schemas.py`,
  `message_builder.py`, and `crash_recovery.py` have zero imports of
  `httpx`/`fastapi`/`supabase`/`app.config`/`app.db`. Keep extending them
  that way rather than folding new decision logic directly into
  `agent_loop.py`, which is already the largest single file in this
  codebase and shouldn't grow the part of it that can't be unit tested.
