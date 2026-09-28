"""
Quan Harness — orchestration backend, Phases 1-3 + 4 (complete: 4.1-4.5).

Owns authentication verification, the data model, and the agent's reasoning
loop — never runs a task's arbitrary shell commands itself (§2), except via
the sandboxed project workspace (§23) added in Phase 2. Phase 1 wires up:
auth, Connections (LLM credentials, the GitHub sync credential, MCP
connectors), Projects + Sessions CRUD, and the deterministic Platform
Operations actions (§24). Phase 2 adds: the Workspace Service, Push/Pull,
checkpoints, and project secrets (§14, §23, §25). Phase 3 adds: the turn
loop, the system prompt, compaction, stuck detection, and the agent-facing
HTTP surface (§16-§19) — see /docs/PHASE3_NOTES.md. Phase 4.1/4.2 add: the
Memory System and Project Knowledge (§20-§21) — see
/docs/PHASE4_1_4_2_NOTES.md. Phase 4.3/4.4 exercised the account-level
connector flow and the New Project flow against real-world cases and fixed
two real gaps — see /docs/PHASE4_3_4_4_NOTES.md. Phase 4.5 adds: Scheduling /
Proactive Scanning (§26) — a per-project recurring check that starts a
session exactly the way a person's message would, with every one of its own
tool calls forced through the Ask-gate regardless of the project's
configured Auto/Ask/Off states — see /docs/PHASE4_5_NOTES.md. That completes
Phase 4 of 9.

Run locally: `uvicorn app.main:app --reload` from the backend/ directory, after
copying .env.example to .env and filling it in (see /docs/YOUR_SETUP_CHECKLIST.md).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    account,
    agent,
    audit_log,
    auth,
    connectors,
    github_credential,
    llm_credentials,
    projects,
    sessions,
    workspace,
)
from app.services import scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # §26, Phase 4.5 — the one background task this backend runs: a poll
    # loop that starts a real session for any project_schedules row that's
    # come due (app/services/scheduler.py). Started here rather than at
    # import time so it only ever runs once per real running process, not
    # once per test/tooling import of this module, and stopped on shutdown
    # so a Render deploy's graceful restart doesn't leave a half-finished
    # tick's DB calls racing the new process's own startup.
    scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title="Quan Harness API",
    version="0.4.5-phase4-complete",
    description="Orchestration backend for Quan Harness — Phase 4 complete (4.1-4.5): Memory System, "
    "Project Knowledge, Connector Integration, Auto-Provisioning, Scheduling.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(account.router)
app.include_router(llm_credentials.router)
app.include_router(github_credential.router)
app.include_router(connectors.router)
app.include_router(projects.router)
app.include_router(sessions.router)
app.include_router(workspace.router)
app.include_router(agent.router)
app.include_router(audit_log.router)


@app.get("/health")
def health():
    return {"status": "ok", "phase": "4.1-4.5"}
