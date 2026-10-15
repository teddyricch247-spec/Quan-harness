# Third-Party Notices

This file exists per §29 of the spec ("Add a `NOTICES.md` ... stating plainly
that ... "), read before any code in this repository was written. It's the
attribution record for anything in Quan Harness that's adapted from another
project's own publicly documented design, as opposed to an ordinary dependency
pulled in through `pip`/`npm` under its own standard license.

## Status by phase

Phase 1 (auth, Connections, Projects/Sessions CRUD, Platform Operations),
Phase 2 (Workspace Service, file tools, Push/Pull, shell), and Phase 3 (turn
loop, system prompt, compaction, stuck detection) are in this codebase now.
All three pieces §29 names as directly drawn on have landed:

| Source | License | What Quan Harness adapts from it | Status |
|---|---|---|---|
| **Aider** (`Aider-AI/aider`) | Apache License 2.0 | The strict, non-fuzzy `str_replace` file-editing discipline (§14.2); the repo-map concept — file paths plus ranked function/class signatures rather than full file contents (§17) | **Landed** — Phase 2 (editing discipline), Phase 3 (repo map) — see the completed entry below |
| **OpenHands** (`All-Hands-AI/OpenHands`) | MIT License | The system prompt (§18) — substantial passages of `IDENTITY_AND_ROLE`, `PROBLEM_SOLVING_WORKFLOW`, `BASH_USAGE`, and related sections are close edits of OpenHands' own wording | **Landed in Phase 3** — see the completed entry below |
| **DeepSeek Harness** (`deepseek-ai/dsh`) | MIT License | The structured-checkpoint compaction instruction and re-injection framing (§17.1), reproduced close to verbatim from DSH's own `dsh-compaction-basic` package, adapted only for this product's `update_plan` naming in place of DSH's `todo_write` | **Landed in Phase 3** — see the completed entry below |

This table's rows are the final notice now that every phase named in the
right-hand column has shipped the corresponding code, same reasoning as
Phase 1 laid out here originally for why it started as placeholders.

## Aider — completed entry (Phase 2)

- **Project:** Aider (`Aider-AI/aider`, formerly `paul-gauthier/aider`),
  created by Paul Gauthier.
- **License:** Apache License, Version 2.0
  (https://github.com/Aider-AI/aider/blob/main/LICENSE.txt).
- **What was adapted:** not code — the *editing discipline* Aider is known
  for: an LLM-driven file edit is only ever applied when the "old" text it
  proposes replacing matches the file's actual content exactly once, with no
  fuzzy or whitespace-tolerant matching and no partial-match fallback. Quan
  Harness's own implementation of that discipline
  (`backend/app/services/text_edit.py`'s `apply_str_replace`, exercised by
  `app/services/file_tools.py`'s `str_replace` tool) is written from scratch
  in Python for this codebase's own architecture — no Aider source was copied.
  Recorded here anyway, at the same conservative standard §29 sets, since the
  technique itself (not merely files inspired by it) is what's being reused.
- **Copyright notice:** Apache-licensed repositories typically ship the
  standard Apache 2.0 license template without a project-specific filled-in
  copyright line (relying on repository/commit history for authorship, per
  Apache's own guidance) — that's the case here too. Attributed to Paul
  Gauthier and the Aider project's contributors. Verify against the upstream
  LICENSE.txt directly if a more specific copyright line is ever needed for a
  particular jurisdiction's compliance requirements.
- **Apache 2.0's actual requirement** (preserve the copyright notice and a
  statement of change on substantial reproduction) is satisfied by this
  entry existing at all, since no source was reproduced verbatim — this is
  the belt-and-braces version of compliance the spec's own conservative
  framing (§29) calls for, not a case where a stricter reading was legally
  required.
- **Addendum, Phase 3 — the repo map:** the second technique this row covers.
  Aider's own repo-map feature sends the model file paths plus ranked
  function/class signatures instead of full file contents, so it can navigate
  a large codebase within a limited context budget. Quan Harness's version
  (`backend/app/services/repo_map.py`) implements the same idea from scratch —
  its own regex-based signature extraction, its own ranking/budgeting rules
  (§17) — no Aider source was copied. What §17 describes as "a lightweight
  PageRank-style pass over a symbol graph" is, honestly, a one-hop adjacency
  boost here, not a real PageRank iteration or Aider's own actual ranking
  algorithm (which does run a real graph-centrality pass over statically
  extracted definition/reference edges) — see `repo_map.py`'s own docstring
  and /docs/PHASE3_NOTES.md's rough-edges section.

## OpenHands — completed entry (Phase 3)

- **Project:** OpenHands (`All-Hands-AI/OpenHands`, formerly OpenDevin), an
  open-source autonomous software engineering agent platform.
- **License:** MIT License
  (https://github.com/All-Hands-AI/OpenHands/blob/main/LICENSE).
- **What was adapted:** the shape and, in places, close wording of an agent
  system prompt covering identity/role framing, an explicit problem-solving
  workflow, shell-usage conventions, and the general register of instructing
  an LLM to act as an autonomous coding agent. Quan Harness's version
  (`backend/app/services/system_prompt.py`'s `STATIC_IDENTITY_AND_ROLE`,
  `STATIC_PROBLEM_SOLVING_WORKFLOW`, `STATIC_BASH_USAGE`, and related
  constants, sourced verbatim from the patched `phase-3-loop-prompt.md` §18
  this phase was built against) is written for this product's own tool set,
  security model, and connector architecture — not a copy of OpenHands'
  actual prompt file, but close enough in structure and phrasing in places
  that §29 calls for this entry to exist regardless.
- **Copyright notice:** MIT-licensed; copyright the OpenHands project and its
  contributors (Copyright (c) OpenHands, per the project's own LICENSE file).
  Verify against the upstream LICENSE directly if a jurisdiction-specific
  copyright line is ever needed.
- **MIT's actual requirement** (include the copyright notice and license text
  in copies/substantial portions) is satisfied by this entry, at the same
  conservative standard applied to Aider's entry above.

## DeepSeek Harness — completed entry (Phase 3)

- **Project:** DeepSeek Harness (`deepseek-ai/dsh`), specifically its
  `dsh-compaction-basic` package.
- **License:** MIT License.
- **What was adapted:** the structured-checkpoint compaction instruction and
  the re-injection framing template §17.1 specifies — reproduced close to
  verbatim from DSH's own package, per the patch this phase was built
  against, adapted only for this product's `update_plan` naming in place of
  DSH's `todo_write`. Lives in `backend/app/services/compaction.py` as
  `COMPACTION_INSTRUCTION` and the `_REINJECTION_TEMPLATE` behind
  `wrap_checkpoint`.
- **Copyright notice:** MIT-licensed; copyright DeepSeek and the DSH
  project's contributors. Verify against the upstream LICENSE directly if a
  jurisdiction-specific copyright line is ever needed.
- **MIT's actual requirement** is satisfied by this entry, at the same
  standard applied to the two entries above — and here more literally, since
  this one really is reproduced close to verbatim rather than only
  structurally similar.


## What a completed entry needs

- The project name, its license, and a link to the exact license text/version
  used.
- A concrete description of what was adapted — which file(s), prompt
  section(s), or algorithm(s), and how closely they follow the source. Not
  "inspired by."
- The upstream copyright notice, reproduced as that license requires.

## Compliance note

Both Apache 2.0 and MIT are permissive: they allow copying, modifying, and
redistributing — including as part of a commercial, closed-source product —
on the condition that the original copyright notice (and, for Apache 2.0, a
notice of what changed) accompanies any substantial reproduction. Neither
license requires royalty, approval, or end-user disclosure; the notice lives
here, in the codebase's own documentation, not in the product's UI. This is
general information, not legal advice — see §29's own closing note.

## Naming and branding

None of Aider, OpenHands, or DeepSeek Harness grants any trademark right to
their names or logos by licensing their code permissively. This product is
named **Quan Harness**, never any of those names, in any user-facing surface.
Referring to them by name in engineering documentation like this file (or in
code comments, describing what was studied or adapted) is fine and expected.

## Ordinary dependencies (Phases 1-3)

Ordinary open-source packages — FastAPI, Next.js, `supabase-py`, PyJWT,
`httpx`, `litellm`, and everything else in `backend/requirements.txt` and
`frontend/package.json` — are used under their own standard licenses
(MIT/Apache-2.0/BSD in every case as of this writing) via normal package
management. That's not "adapted code" in the sense this file and §29 are
about, so it doesn't need an entry here. The Fly.io Machines API (Phase 2's
Workspace Service) and each project's own configured LLM provider API
(Phase 3, via `litellm`) are accessed as plain HTTP APIs under Quan Harness's
own account terms / the person's own credential, not as embedded/adapted
code either.
