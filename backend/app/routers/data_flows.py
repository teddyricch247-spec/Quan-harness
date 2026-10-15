"""
§23.10, fifth bullet (Phase 5.6) — "Be explicit and honest in-product about exactly what leaves the workspace and when."
GET /projects/{id}/data-flows: the statement itself (app/services/data_flows.py, pure), made specific to THIS project — which
model, which repository, which connectors, whether the agent can take screenshots and why not if it can't.

Names and wording only. Never a URL of a connector, never a credential or a reference to one (tests/test_data_flows.py pins it).
"""
from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.core.security import AuthedUser
from app.dependencies import verified_user
from app.models.schemas import AgentBrowserStatusOut, DataFlowOut, DataFlowsOut
from app.repositories import mcp_servers as mcp_servers_repo
from app.repositories import projects as projects_repo
from app.services import data_flows as data_flows_service
from app.services import llm_client, visual_qa
from app.services import visual_qa_rules as visual_qa_rules

router = APIRouter(tags=["data-flows"])


@router.get("/projects/{project_id}/data-flows", response_model=DataFlowsOut)
async def get_data_flows(project_id: str, user: AuthedUser = Depends(verified_user)) -> DataFlowsOut:
    project = await projects_repo.get_for_user(user.user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    try:
        credential = await llm_client.resolve_credential(project)
    except llm_client.NoLlmCredentialError:
        llm_label = None
        availability = visual_qa_rules.decide_browser_availability(
            server_enabled=get_settings().agent_browser_enabled,
            runtime_available=visual_qa.runtime_available(),
            vision_confirmed=False,
            model_label="no model connected",
        )
    else:
        llm_label = f"{credential.provider} / {credential.model}"
        availability = visual_qa.availability_for(credential)

    granted = set(await projects_repo.get_connector_access(project_id))
    servers = await mcp_servers_repo.list_for_user(user.user_id)
    connector_names = tuple(s["name"] for s in servers if s["id"] in granted and s.get("enabled", True))

    flows = data_flows_service.build_data_flows(
        data_flows_service.DataFlowFacts(
            llm_label=llm_label,
            github_repo=project.get("github_repo"),
            connector_names=connector_names,
            browser_available=availability.available,
            browser_unavailable_reason=availability.reason,
        )
    )
    return DataFlowsOut(
        flows=[DataFlowOut(id=f.id, title=f.title, when=f.when, where=f.where, sends=list(f.sends), never=list(f.never), caveat=f.caveat) for f in flows],
        agent_browser=AgentBrowserStatusOut(available=availability.available, code=availability.code, reason=availability.reason),
    )
