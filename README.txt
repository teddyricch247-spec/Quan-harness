Quan-harness fixes

1. Unzip at the repo root (the folder that contains backend/).
2. Run:  python apply_fix.py
   Edits 3 files in place. Each file is applied on its own and all-or-nothing; a file whose text doesn't match
   GitHub main is skipped with a message and the others still apply. Safe to re-run.
3. Optional: pytest backend/tests/test_view_range_regression.py backend/tests/test_static_site_and_preview_rules.py
4. Commit the 3 edited files under backend/app/services/ and the 2 new test files under backend/tests/, push.

agent_loop.py
- _as_range(): no more len() on a view_range that isn't a list (the model sent view_range: 120).
- _execute_call(): a tool that raises becomes a failed tool_result instead of killing the turn and leaving a
  dangling tool_call that crash recovery re-runs (and re-crashes on) at the start of every later message.

deploy_detection.py
- A folder with index.html and no package.json / requirements.txt / Procfile / manage.py / app.py / main.py is
  detected by rule: run_cmd "python3 -m http.server $PORT", port 8000, no build step. Before, that case depended
  on the fallback model happening to answer with a file server.
- stack is labelled "python" because deploy_runs_stack_check only allows nextjs/node/python/dockerfile/llm_fallback.

system_prompt.py
- New PREVIEW_RULES static block (after VISUAL_VERIFICATION) telling the agent the preview's limits: one app from
  the repo root, one public port, opens at "/" with no address bar, static files vs Deploy, saved start command.
  This changes the cached static prompt prefix once; prompt caching re-warms on the next call.
