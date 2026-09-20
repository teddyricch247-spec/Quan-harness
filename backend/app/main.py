"""
Quan Harness — orchestration backend, Phases 1-3.

Owns authentication verification, the data model, and the agent's reasoning
loop — never runs a task's arbitrary shell commands itself (§2), except via
the sandboxed project workspace (§23) added in Phase 2. Phase 1 wires up:
auth, Connections (LLM credentials, the GitHub sync credential, MCP
connectors), Projects + Sessions CRUD, and the deterministic Platform
Operations actions (§24). Phase 2 adds: the Workspace Service, Push/Pull,
checkpoints, and project secrets (§14, §23, §25). Phase 3 adds: the turn
loop, the system prompt, compaction, stuck detection, and the agent-facing
HTTP surface (§16-§19) — see /docs/PHASE3_NOTES.md.

Run locally: `uvicorn app.main:app --reload` from the backend/ directory, after
copying .env.example to .env and filling it in (see /docs/YOUR_SETUP_CHECKLIST.md).
"""
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

settings = get_settings()

app = FastAPI(
    title="Quan Harness API",
    version="0.3.0-phase3",
    description="Orchestration backend for Quan Harness — Phase 3: turn loop, system prompt, compaction, stuck detection.",
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
    return {"status": "ok", "phase": 3}
