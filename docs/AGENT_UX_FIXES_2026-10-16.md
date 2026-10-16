# Agent UX fixes, 2026-10-16

| Problem | Cause | Fix | File |
|---|---|---|---|
| Preview iframe shows an old page | Frame loaded only by Open/Reload click; never reloaded after the agent edits files | `refreshSignal` bumps on successful `str_replace` / `create_file` / `preview_rebuild`, on turn end, and when a deploy flips running to success; open frame reloads (1.2 s debounce) | `ChatPane.tsx`, `PreviewPanel.tsx`, `PreviewTab.tsx`, `app/projects/[id]/page.tsx` |
| Preview address is new, frame is old | Proxy forwarded upstream `Last-Modified` with no `Cache-Control`; browsers cache heuristically | Proxy strips `Cache-Control`/`ETag`/`Last-Modified`/`Expires`/`Age`/`Pragma`, sends `Cache-Control: no-store` | `preview_rules.py` |
| Messages unformatted, no tables | `ChatPane` rendered agent text as `whitespace-pre-wrap` | Typed Markdown parser + React renderer (tables, lists, code, links), no `dangerouslySetInnerHTML` | `lib/markdown.ts`, `components/Markdown.tsx` |
| Chatty, long replies | `COMMUNICATION_STYLE` described a style but set no contract; step 2 told the model to narrate a plan | New output contract: banned filler, fixed final-report shape, hard length limits, tables for multi-attribute data | `system_prompt.py` |
| Agent says "no browser tools" with no reason | Static prompt promised a headless browser while the dynamic notice denied it | Static blocks no longer promise it; agent must name the missing tool and the reason | `system_prompt.py` |

Tests added: `frontend/scripts/test-markdown.ts` (34 checks, `npx tsx scripts/test-markdown.ts`), two in `backend/tests/test_system_prompt.py`, one in `backend/tests/test_preview_rules.py`.

Not verified: `next build`, a browser or phone render, pytest (no network for installs in the build environment). The markdown parser, the header rule and the prompt text were run directly with Node / plain Python.
Deploy: backend (Render) and frontend (Vercel) both need the new commit.
