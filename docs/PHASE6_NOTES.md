> **Reconciliation note (2026-10-13).** This is the Phase 6 write-up as originally produced, on a Phase 5.8 base. In THIS
> tree: (1) migrations are numbered `0013`–`0015` as written, but the presets/Ling migrations moved to `0016`/`0017`; (2) the
> Phase 5.6–5.8 modules it refers to (`visual_qa`, `sub_agent`, …) exist here as a *reconstruction* — see
> `docs/PHASE5_6_5_7_5_8_NOTES.md`; (3) the 21-test agent-loop wiring test is parked in `docs/phase6-pending/` until its
> harness (`test_agent_loop_phase5_wiring.py`'s `World`) is rebuilt; (4) the picture UI lives in the Convert chat pane
> (`ChatPane`, + sheet → "Add an image"). Everything else below applies as written. See `docs/RECONCILIATION_NOTES.md`.

# Phase 6 — image input (step 19) and account-isolation verification (step 20)

Written 2026-10-07. **Migrations `0013`–`0015` were applied to the live project on 2026-10-08** (dry run → apply → verify; see "Applying").

## What this phase delivers

| | What | Where |
|---|---|---|
| 19 | Pictures attached to a user message reach a vision-capable model as image content | `services/image_input.py`, `services/message_builder.py`, `services/agent_loop.py`, `routers/agent.py`, `repositories/session_attachments.py`, `0013`, `frontend/lib/attachments.ts` |
| 20 | Isolation verification across raw queries, the backend's own API, the database catalog, and the shared-workspace gates — wired into CI | `tests/test_isolation_*.py`, `tests/isolation_registry.py`, `tests/conftest.py`, `.github/workflows/isolation.yml`, `0014`, `0015` |

## Step 19 — image input

**Flow.** `POST /sessions/{id}/attachments` (JSON, base64) → validated from the file's own bytes → stored in
`session_attachments` → returns `{id, filename, media_type, width, height, byte_size}`. The message that follows
(`POST /sessions/{id}/messages` or `/interrupt`) names the ids in `attachment_ids`. `start_turn` / `send_interrupt`
claim them atomically, write the user event with **metadata only**, then link the claim to the event id. Each loop
iteration loads the few most recent pictures and `message_builder` puts them on the user's own message as `image_url`
parts. `GET /sessions/{id}/attachments/{att_id}` returns the bytes (owner only) for transcript thumbnails.

**Decisions worth knowing**

- *Pixels never go in `session_events`.* Same rule §14.9 already applies to the agent's browser screenshots, same
  reason (every client would re-receive them; every token estimate would count them).
- *The file's bytes decide, not the client.* Type and dimensions are read from the header (PNG, JPEG, GIF, WebP incl.
  lossless/extended); a declared type that disagrees is refused. Checked against real Pillow output for all four.
- *Limits:* 3 MiB, 8000 px a side, 4 per message, 12 waiting per session, 6 shown per model call (newest first;
  older ones become a one-line note — and compaction drops them with the part of the log they sit in).
- *The model must be confirmed to read images* (`visual_qa.credential_supports_vision` — litellm's table or the
  operator's `AGENT_VISION_MODELS`), checked at upload AND at send (the model may change in between). Fail-closed:
  an unknown model is "not confirmed". If a provider rejects an image anyway, the call is retried once without it;
  only a successful retry turns image input off for the session, an outage doesn't.
- *Claim / link / release are SQL functions* (service role only) so the backend never makes PostgREST echo a
  multi-MB row back just to learn which rows changed. A claim is one `UPDATE … WHERE message_event_id IS NULL`, so two
  messages can never own one picture. Uploads never attached are purged after an hour, opportunistically at upload time.
- *A real bug found on the way:* `_vision_rejected_sessions` also drives the browser tools' availability, so a rejected
  user picture would have posted "the browser tools were switched off" on a server where they were never on.
  `_browser_availability` now returns the operator's own `server_off` answer in that case (tested).
- `data_flows` now says attached pictures go to the provider unmasked and are kept with the conversation.

**Not built:** the chat UI. The pane still says "not built yet", so there is no attach button. `frontend/lib/attachments.ts`
is everything the message box needs (shrink to 1568 px and re-encode in the browser — which also drops EXIF/GPS —
upload, send, and a token-authenticated thumbnail fetch). It type-checks under `strict`; it has not run in a browser.

## Step 20 — isolation verification

**What the suite found, on the live database, before any fix** (rolled-back dry run, account B writing through
PostgREST with its own token): twelve forged writes were **accepted** — B's rows pointing at A's connector
(`project_mcp_access.mcp_server_id`), A's session (`checkpoints`, `project_memory_log`, `audit_log`,
`project_schedules.last_session_id`), A's schedule (`sessions.schedule_id`), A's deploy run, A's event
(`session_events.parent_event_id`), A's project (`audit_log`), and A's workspace handle — plus two references that
crossed between two projects of one account. Nothing of A's was readable through any of them and the backend
re-checks ownership, so none was a live leak. But several are `NO ACTION`/`CASCADE` foreign keys, so B's row could make
A's own delete **fail** (or A's delete silently remove B's rows). The three `projects` credential references were
already refused by the `check_*_credential_owner` triggers.

**`0014`** adds the missing `WITH CHECK` conditions to eight owner policies (USING untouched, so what anyone can see is
unchanged), two small `SECURITY DEFINER` helpers in a non-exposed `private` schema (a plain sub-select would recurse:
`sessions` ↔ `project_schedules`, and `session_events` referencing itself), and a unique index on
`project_workspaces.sprite_handle` (two projects must never name one workspace machine; the table is empty).
Dry-run result, same transaction: all 12 forged writes refused (`42501`; `23505` for the handle), and 12 legitimate
writes (own project, own refs) all still accepted.

**The suite**

- `test_isolation_matrix.py` — from `isolation_registry.py`, for **every** table (22): read, update, delete, insert-into-A's-scope, move-own-row-into-A's-scope;
  for every declared cross-reference: new row and re-point; same-account/different-project; anonymous callers;
  the functions clients must not call; handle uniqueness. Catalog guards (via `rls_audit`, `0015`): every table
  registered, RLS on, a policy, every policy keyed on `auth.uid()`, every foreign key between owned tables declared,
  and no function in `public` callable by a client except the audit. A new table or foreign key **fails the build**
  until registered — six tables had silently gone untested after Phase 4.
- `test_isolation_api.py` — the real app in-process, called as B with A's ids. The sweep is **generated from the
  app's route table** (every route with an id, every kind of A resource that id could be, every method; every list
  endpoint scanned for A's strings), with a control group (A must succeed on its own database-only reads — the SSE stream and the sandbox-calling
  routes are deliberately left out, the first never ends under the in-process TestClient — or B's 404s prove nothing), an unauthenticated sweep, and an "A is byte-for-byte unchanged" check. An id parameter it can't fill
  fails the run instead of being skipped.
- `test_isolation_concurrency.py` (offline, 5 tests) — the §23.4 gates are keyed by project/session, never global:
  one account's git sync or running turn cannot block, or be observed by, another's.

**CI** — `.github/workflows/isolation.yml`: PRs touching `db/migrations/**` (and the tests / repositories / routers),
pushes to main, **weekly** (a policy edited by hand in the dashboard appears in no PR), and on demand. `raw-rls` needs
only the anon key and the two accounts. `api` needs the service-role key and is **off** until you set the repository
variable `ISOLATION_API_ENABLED=true` — and that key must belong to a **dedicated** Supabase project, never production.
A missing secret fails the run (`ISOLATION_REQUIRED=1`); it never silently skips. A workflow with a `paths` filter
reports nothing on PRs outside those paths, so don't mark it a *required* check unless you drop the filter.

## Applying — DONE on 2026-10-08

Applied through the Supabase connector in order: `0013`, `0014`, `0015`, then a fourth entry, `phase6_advisor_fixes`.
Verified on the live project afterwards (every check below ran against the real policies, in a block that rolls back):

- all 13 forged writes by account B refused (`42501`; `23505` for the duplicate workspace handle) — including the one my
  object-count query had seemed to miss (that was a capitalisation slip in my own query, not a missing policy);
- all 10 legitimate writes by B (its own project, its own references, its own attachment) still accepted; B reads 0 of
  A's attachments;
- catalog guards: 22 tables, none without RLS, no policy lacking `auth.uid()`, `rls_audit` the only function a client can
  call, 33 foreign keys;
- the attachment functions are callable by `service_role` only, and a real claim → link → release round-trip works as
  `service_role`; a second claim of the same pictures gets nothing;
- no residue (no leftover test users or rows).

**Supabase's security advisor, run afterwards, found two things in what I had just applied, now fixed:** the three
attachment functions had no pinned `search_path`, and `rls_audit` was `SECURITY DEFINER` although everything it reads is
readable by any role (now `SECURITY INVOKER`). The advisor's remaining findings are not from this phase: three older
trigger functions (`check_github_credential_owner`, `check_llm_credential_owner`, `projects_preview_subdomain_immutable`)
also lack a pinned `search_path`, and **leaked-password protection is switched off** for Supabase Auth (Authentication →
Providers → Email → password security; a dashboard toggle I can't set from here).

**Still to do on your side:** deploy the new backend to Render (image upload needs it), and add the CI secrets
(`docs/YOUR_SETUP_CHECKLIST.md`) so the isolation workflow can run — the suite itself has not run against the live
database yet; only its premises have (above). The cross-reference tests should now pass rather than fail.

**Rollback.** `0013`: `drop table session_attachments;` and the three functions. `0015`: `drop function public.rls_audit();`.
`0014`: `drop index project_workspaces_sprite_handle_key;`, `drop schema private cascade;` **after** restoring these
`WITH CHECK`s with `alter policy <name> on <table> with check (…)`:
`audit_log_owner_all` → `(user_id = auth.uid())`; `session_events_owner_all` → `exists (select 1 from sessions s join
projects p on p.id = s.project_id where s.id = session_events.session_id and p.user_id = auth.uid())`; and
`project_mcp_access_`, `checkpoints_`, `project_memory_log_`, `project_notifications_`, `project_schedules_`,
`sessions_owner_all` → `exists (select 1 from projects p where p.id = <table>.project_id and p.user_id = auth.uid())`.

## Verified, and how

- `image_input` (71 tests with message_builder's existing ones), the wiring through the REAL `_run_inner`, `start_turn`,
  `send_interrupt` and the vision gate (21 tests), the concurrency gates (5), the registry's internal consistency, the
  data-flows disclosure: **run**, in a sandbox with stand-ins for the modules/packages that weren't available (the
  overlay is a subset of the repo; no `pytest`/`fastapi`/`pydantic`/`supabase`, no network). Baseline before my edits
  and after: the same 19 of 21 existing wiring tests pass; the two that don't depend on the real `crash_recovery` /
  `stuck_detector`, which the sandbox stood in for. **Run `pytest` yourself — that is the real regression run.**
- `0013`, `0014`, `0015`: each dry-run first in a block that always raises (so it rolled back), with two simulated
  signed-in users; then applied and re-verified live (see "Applying").
- All 55 insert payloads the registry builds, replayed against the live schema (columns, NOT NULLs, CHECKs, FKs, the
  partial unique index on open notifications) — one real factory problem found and fixed that way (an attack row would have collided with the base row's unique index and hidden a missing RLS check behind a different error).
- `frontend/lib/attachments.ts`: `tsc --strict` against stubs for the project's own modules.

## NOT verified

- **The live suite has never run.** `test_rls_isolation.py`'s new neighbours, the matrix and the API sweep need a real
  Supabase with the two accounts; no network here. Their *premises* (that each forged write is accepted today and
  refused after `0014`) are what the dry runs proved; the Python around them is syntax-checked, collected, and the
  helpers exercised, not executed end to end. Expect to fix a typo or two on the first real run.
- A real provider's reaction to an image; the image path against a real model.
- That a ~4 MB base64 string passes through Supabase's HTTP gateway in one insert (the 3 MiB cap was chosen to stay
  far from any limit, but I could not measure it). A client that shrinks first sends ~100–600 KB.
- `litellm` 1.55.4 predates many vision models: until you list a model in `AGENT_VISION_MODELS`, attaching to it is refused with that instruction.

## Known gap — left open on purpose

Seven columns hold vault secret ids (`llm_credentials.api_key_ref`, `github_credentials.token_ref`,
`mcp_servers.{auth_token_ref, oauth_client_secret_ref, oauth_session_ref}`, `preview_secrets.secret_ref`,
`project_secrets.secret_ref`). They have no foreign key and a signed-in client can write them, so B's row could name a
vault id that belongs to A. Exploiting it needs A's id — a random uuid no client is ever shown — so it isn't exploitable
today, but it is the one place isolation rests on an id staying secret. The existing RLS suite seeds those columns through the
client, which is why I did not just block it. Options: (1) a trigger refusing client writes to `*_ref` columns, and
seeding them in tests via the service role (needs a dedicated CI project); (2) revoke client write privileges on
server-managed tables altogether (the frontend only uses Supabase for auth); (3) accept. It is pinned as a `strict`
expected-failure test, so fixing it makes the run fail until the marker is removed. Your call.

## Rough edges

- GIFs are stored as uploaded (animated stays animated server-side); the browser helper flattens to the first frame. EXIF is
  stripped only by that helper — an API caller's pictures are forwarded as sent, and `data_flows` says nothing is masked.
- The picture count in context (6) and the pre-call token estimate (1600 per image) are rough constants.
- The API sweep treats a `422` (invalid empty body) as "unexercised", prints the list, and relies on `CURATED_BODIES`
  for the routes that matter; routes I haven't read (`deploy`, `preview`, `connectors`, …) get an empty body and will
  mostly be in that list — add a body to `CURATED_BODIES` to test them for real.
- `image_input_problem` duplicates `llm_client.resolve_credential`'s choice of credential (project's own, else the
  account default) without reading the vault; if that rule changes, change both.
