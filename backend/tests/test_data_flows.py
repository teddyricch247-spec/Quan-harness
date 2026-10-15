"""§23.10, fifth bullet — what leaves the workspace, and when (app/services/data_flows.py + its endpoint).

The completeness of the disclosure against the code is pinned in test_security_checklist.py (the set of modules that
can call a model; the set of hosts the backend names). This file pins what the screen SAYS: that it is specific to the
project, that each protection claimed is stated alongside its honest limit, and that the endpoint hands out names
and wording only — never a credential."""
import asyncio
import re
from types import SimpleNamespace as NS
from unittest import mock

import pytest

from app.routers import data_flows as router
from app.services import data_flows as df


def _flows(**facts):
    return {f.id: f for f in df.build_data_flows(df.DataFlowFacts(**facts))}


def _text(flow: df.DataFlow) -> str:
    return " ".join([flow.title, flow.when, flow.where, *flow.sends, *flow.never, flow.caveat or ""])


def test_every_flow_is_complete_and_ids_are_unique():
    flows = df.build_data_flows(df.DataFlowFacts(llm_label="a / b", github_repo="me/app", connector_names=("Linear",), browser_available=True))
    assert len({f.id for f in flows}) == len(flows)
    for f in flows:
        assert f.title and f.when and f.where and f.sends, f.id
        assert all(isinstance(line, str) and line.strip() for line in (*f.sends, *f.never)), f.id


def test_an_unconfigured_project_still_gets_an_accurate_shorter_picture():
    flows = _flows()
    assert set(flows) == {"llm", "github_push", "github_pull", "workspace_host", "preview", "harness_db"}   # no connectors row without connectors
    assert "None is connected yet, so nothing is sent" in flows["llm"].where
    assert "Nothing is sent until you connect GitHub and press Push" in flows["github_push"].where


def test_the_model_provider_row_names_the_actual_model_and_lists_what_it_receives():
    llm = _flows(llm_label="anthropic / claude-x")["llm"]
    assert "anthropic / claude-x" in llm.where
    text = _text(llm)
    for must in ("messages", "repository", "contents of every file", "output of every command", "summary of what the agent did", "build or start log"):
        assert must in text, must


def test_screenshots_are_disclosed_only_when_the_agent_can_take_them_and_always_with_their_limit():
    with_browser = _flows(llm_label="x / y", browser_available=True)["llm"]
    without = _flows(llm_label="x / y", browser_available=False)["llm"]
    assert any("Screenshots" in line for line in with_browser.sends) and "can't be masked" in (with_browser.caveat or "")
    assert not any("Screenshots" in line for line in without.sends) and without.caveat is None   # no claim about a thing that isn't happening


def test_attached_pictures_are_disclosed_with_their_limit_even_when_the_browser_is_off():
    # Phase 6.1: a picture the person attaches goes to the model provider and is stored with the conversation.
    for browser in (True, False):
        line = next(l for l in _flows(llm_label="x / y", browser_available=browser)["llm"].sends if "Pictures you attach" in l)
        assert "kept with the conversation" in line and "is masked" in line and "will see it" in line


def test_it_says_secrets_are_masked_and_that_tokens_never_reach_the_model():
    never = " ".join(_flows(llm_label="x / y")["llm"].never)
    assert "masked before any text reaches the model" in never and "GitHub token" in never


def test_push_is_user_only_and_discloses_everything_it_does():
    push = _flows(github_repo="me/app")["github_push"]
    assert "Only when you press Push" in push.when and "cannot push" in push.when
    body = _text(push)
    assert "me/app" in push.where and "harness/workspace" in push.where
    assert "squashed" in body and "creates one in your GitHub account" in body and "opens a pull request" in body
    assert ".gitignore" in (push.caveat or "") and ".env" in (push.caveat or "")   # the honest limit: ignore rules are all that protect a .env


def test_the_broad_github_permission_is_stated_not_hidden():
    # Checklist item 4 (short-lived, least-privilege tokens) is NOT MET for 'Connect with GitHub'. The honest control
    # is to say so, in the place the person decides, and to name the safer option.
    pull = _flows()["github_pull"]
    assert "broad" in (pull.caveat or "") and "'repo'" in (pull.caveat or "") and "fine-grained" in (pull.caveat or "")
    assert "never written into the workspace's files or git configuration" in " ".join(pull.never)


def test_connectors_appear_by_name_with_their_limit():
    connectors = _flows(connector_names=("GitHub", "Linear"))["connectors"]
    assert "GitHub, Linear" in connectors.where and "comes back into the agent's context" in (connectors.caveat or "")


def test_preview_row_carries_the_reason_the_agents_browser_is_unavailable():
    unavailable = _flows(browser_available=False, browser_unavailable_reason="The model can't read images.")["preview"]
    assert unavailable.caveat == "The model can't read images."
    assert _flows(browser_available=True)["preview"].caveat is None
    assert "not available" in (_flows(browser_available=False)["preview"].caveat or "")   # a sensible default when no reason is given


def test_the_text_is_plain_language_for_the_person_who_owns_the_project():
    for f in df.build_data_flows(df.DataFlowFacts(llm_label="a / b", github_repo="me/app", connector_names=("X",), browser_available=True)):
        text = _text(f)
        assert "§" not in text and not re.search(r"\b(litellm|sub-agent|vault|jwt|rls|ssrf)\b", text, re.IGNORECASE), f.id
        assert not re.search(r"\b[a-z_]+\.py\b|app/services", text), f.id
        assert not re.search(r"(ghp_|sk-[A-Za-z0-9]|eyJ[A-Za-z0-9])", text), f.id   # and it never contains anything credential-shaped


# --- the endpoint -------------------------------------------------------------------------------------------------


def _call(project, *, credential=NS(provider="anthropic", model="claude-x"), granted=("s1",), servers=(), availability=None):
    from app.services import visual_qa_rules as rules

    avail = availability or rules.BrowserAvailability(True, "ok", "", "", False)
    patches = [
        mock.patch.object(router.projects_repo, "get_for_user", mock.AsyncMock(return_value=project)),
        mock.patch.object(router.llm_client, "resolve_credential",
                          mock.AsyncMock(return_value=credential) if credential else mock.AsyncMock(side_effect=router.llm_client.NoLlmCredentialError("none"))),
        mock.patch.object(router.visual_qa, "availability_for", lambda c: avail),
        mock.patch.object(router.projects_repo, "get_connector_access", mock.AsyncMock(return_value=list(granted))),
        mock.patch.object(router.mcp_servers_repo, "list_for_user", mock.AsyncMock(return_value=list(servers))),
    ]
    for p in patches:
        p.start()
    try:
        return asyncio.run(router.get_data_flows("P1", NS(user_id="U1")))
    finally:
        for p in patches:
            p.stop()


def test_the_endpoint_is_404_for_a_project_that_is_not_yours():
    with pytest.raises(router.HTTPException) as err:
        _call(None)
    assert err.value.status_code == 404


def test_the_endpoint_is_specific_to_the_project_and_returns_names_only():
    servers = [{"id": "s1", "name": "Linear", "enabled": True, "url": "https://secret-host.example/mcp", "auth_token_ref": "vault://abc"},
               {"id": "s2", "name": "NotGranted", "enabled": True}, {"id": "s3", "name": "Disabled", "enabled": False}]
    out = _call({"id": "P1", "github_repo": "me/app"}, granted=("s1", "s3"), servers=servers)
    by_id = {f.id: f for f in out.flows}
    assert "anthropic / claude-x" in by_id["llm"].where and "me/app" in by_id["github_push"].where
    assert "Linear" in by_id["connectors"].where
    assert "NotGranted" not in by_id["connectors"].where and "Disabled" not in by_id["connectors"].where   # only granted AND enabled
    dumped = str(out.__dict__) + str([f.__dict__ for f in out.flows])
    assert "secret-host.example" not in dumped and "vault://" not in dumped                                 # no URL, no credential reference


def test_with_no_llm_credential_the_endpoint_still_answers_and_says_nothing_is_sent():
    out = _call({"id": "P1", "github_repo": None}, credential=None, granted=())
    assert "nothing is sent" in next(f for f in out.flows if f.id == "llm").where
    assert "connectors" not in {f.id for f in out.flows}


def test_the_agent_browser_status_reports_why_when_unavailable():
    from app.services import visual_qa_rules as rules

    no_vision = rules.decide_browser_availability(server_enabled=True, runtime_available=True, vision_confirmed=False, model_label="x/y")
    out = _call({"id": "P1"}, availability=no_vision, granted=())
    assert out.agent_browser.available is False and out.agent_browser.code == "no_vision" and "x/y" in out.agent_browser.reason
