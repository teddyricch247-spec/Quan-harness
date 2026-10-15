"""
§23.10, fifth bullet — "Be explicit and honest in-product about exactly what leaves the
workspace and when." (Phase 5.6.)

Before this module the product said nothing: there was no screen, string or endpoint that told
a person what their code and conversations are sent to, or when. This is that statement, as data
(`build_data_flows`), shown by the project page and served at GET /projects/{id}/data-flows.

Two rules for editing it:

  1. It must be TRUE. Every claim below was checked against the code that does the thing (the
     list of what each LLM call sends was read from agent_loop / memory_extraction / deploy_pipeline /
     deploy_diagnosis; the Push contents from git_sync + checkpoints), and
     tests/test_security_checklist.py pins the two facts that make it complete — the set of modules
     that can call a model, and the set of external hosts the backend names — so a NEW way for data to
     leave fails a test and forces this file to be reviewed, instead of silently making the screen a
     lie of omission. When you add one, add its row here in the same change.

  2. It is plain language for the person who owns the project, not a policy document. "What is sent",
     "what is not", and one honest caveat where the protection has a known limit. Where a limit exists
     it is stated, not hidden — a screenshot can't be masked; a broad GitHub token is broad.

Pure: no I/O. The router gathers the facts (which model, which repo, which connectors) and passes them in.
"""
from __future__ import annotations

from dataclasses import dataclass

# Every external host the backend's own code names. test_security_checklist.py fails if app/ starts naming a
# host that isn't here — i.e. if data can start going somewhere this screen doesn't explain. (Hosts that are
# CONFIGURATION — the Supabase project, the LLM provider, a connector's URL, a project's own Sprite URL —
# are covered by their own rows below rather than listed here.)
KNOWN_EGRESS_HOSTS = frozenset(
    {
        "github.com",          # Push / Pull (git_sync) and the OAuth sign-in
        "api.github.com",      # OAuth token exchange + "who am I" (github_oauth)
        "api.sprites.dev",     # the workspace platform (Fly.io Sprites)
        "docs.sprites.dev",    # a documentation link in an error message — no data is sent
        "sprites.dev",         # a documentation link in an error message — no data is sent
        "127.0.0.1",           # local only
        "localhost",           # local only
    }
)

# Every module that can send text to a language model. Tool-less except the agent loop (§23.2: "the boundary
# is tool access, not model involvement"). test_security_checklist.py fails if another module starts calling
# one — a new model call is a new thing that data leaves to.
LLM_CALLING_MODULES = frozenset(
    {
        "app.services.agent_loop",         # the turn loop, delegated sub-tasks, and conversation summarising
        "app.services.deploy_diagnosis",   # why a deploy / the page's console failed
        "app.services.deploy_pipeline",    # build plan for a stack the rules don't recognise
        "app.services.memory_extraction",  # updating project / personal memory after a turn
    }
)


@dataclass(frozen=True)
class DataFlow:
    id: str
    title: str
    when: str                   # what triggers it, and who
    where: str                  # who receives it
    sends: tuple[str, ...]      # what leaves
    never: tuple[str, ...] = ()  # what is deliberately not sent / how it's protected
    caveat: str | None = None   # the honest limit, if the protection has one


@dataclass(frozen=True)
class DataFlowFacts:
    """What the router knows about THIS project. Everything is optional: an unconfigured project still gets an
    accurate (shorter) picture."""

    llm_label: str | None = None             # "anthropic / claude-…" — None if no provider is connected
    github_repo: str | None = None           # "owner/repo" — None until first Push or an Import
    connector_names: tuple[str, ...] = ()    # connectors granted to this project and enabled
    browser_available: bool = False          # the agent can take screenshots of the running app
    browser_unavailable_reason: str = ""


def build_data_flows(facts: DataFlowFacts) -> list[DataFlow]:
    flows: list[DataFlow] = []

    # --- the language model -------------------------------------------------------------------------------
    if facts.llm_label:
        llm_where = f"{facts.llm_label} — the model provider you connected"
    else:
        llm_where = "The model provider you connect under Connections → LLM Providers. None is connected yet, so nothing is sent."
    sends = [
        "Your messages to the agent, and the project's instructions and saved memory.",
        "A map of your repository: file paths and function/class signatures.",
        "The contents of every file the agent opens.",
        "The output of every command the agent runs, and any tool results from connectors.",
        "Pictures you attach to a message, exactly as you attached them (they are kept with the conversation). "
        "Nothing in a picture is masked: if it shows a secret, a model that can see images will see it.",
        "At the end of a turn: a summary of what the agent did, so project memory can be updated.",
        "When a conversation gets long: the earlier part of it, so it can be summarised.",
        "When a deploy fails: the build or start log, to explain what went wrong. For a stack the rules don't "
        "recognise: the names of the files in the project's top-level directories (not their contents).",
    ]
    if facts.browser_available:
        sends.append("Screenshots of your running app, and its browser console output, when the agent checks its own work.")
    flows.append(
        DataFlow(
            id="llm",
            title="Your AI model provider",
            when="Every time the agent works on your project — each time it asks the model what to do next.",
            where=llm_where,
            sends=tuple(sends),
            never=(
                "The values of your Live Preview secrets: they are masked before any text reaches the model, in tool output, deploy logs and browser console output alike.",
                "Your GitHub token, the workspace platform's token, and any API key — none of them is ever placed in what the model reads.",
            ),
            caveat=(
                "A screenshot can't be masked. If your running app shows a secret on screen, a model that can see images will see it."
                if facts.browser_available
                else None
            ),
        )
    )

    # --- GitHub: Push -------------------------------------------------------------------------------------
    repo_label = facts.github_repo or "the GitHub repository you link"
    flows.append(
        DataFlow(
            id="github_push",
            title="GitHub — Push",
            when="Only when you press Push. The agent cannot push, and has no GitHub credential to push with.",
            where=f"GitHub, {repo_label}, on the branch harness/workspace."
            if facts.github_repo
            else "GitHub, in the repository you link. Nothing is sent until you connect GitHub and press Push.",
            sends=(
                "One commit containing the workspace as of its latest saved checkpoint — every file not excluded by the project's .gitignore. The workspace's step-by-step history is squashed into that one commit, added on top of whatever you pushed last time.",
                "If no repository is linked yet, Push first creates one in your GitHub account (you choose its name and whether it's private). It also opens a pull request from harness/workspace into your default branch when there isn't one open.",
            ),
            never=("Anything on a schedule or at the agent's own initiative — Push happens only on your click.",),
            caveat=(
                "Files the workspace's .gitignore doesn't exclude are pushed — including a .env file if one is there. "
                "Check what's in the workspace before you push to a public repository."
            ),
        )
    )

    # --- GitHub: Pull + the token's reach ------------------------------------------------------------------
    flows.append(
        DataFlow(
            id="github_pull",
            title="GitHub — Pull and your GitHub access",
            when="Only when you press Pull (and once when you import a repository).",
            where="Your workspace receives files from GitHub; GitHub receives only the request for them.",
            sends=("Your GitHub access token, to authenticate that request — over an encrypted connection, for that one operation.",),
            never=(
                "The token is never written into the workspace's files or git configuration, and the agent never sees it.",
                "Pull asks you first when it would overwrite changes in the workspace.",
            ),
            caveat=(
                "How far that token reaches is whatever you granted when you connected. 'Connect with GitHub' asks for GitHub's broad "
                "'repo' permission, which covers every repository your account can access. A fine-grained token limited to this one "
                "repository (Connections → GitHub → add a token manually) is the safer choice."
            ),
        )
    )

    # --- where the workspace lives -------------------------------------------------------------------------
    flows.append(
        DataFlow(
            id="workspace_host",
            title="Where your project runs",
            when="Always: this is where your code lives and where the agent's commands run.",
            where="Fly.io (the Sprites workspace platform), in a workspace dedicated to this project.",
            sends=(
                "Your project's files and its git history, installed dependencies, and the running Live Preview app — including the values of the preview secrets you set, which the running app needs.",
                "Every command the agent runs executes there.",
            ),
            never=("Other people's projects share none of it: each project has its own workspace.",),
        )
    )

    # --- connectors ----------------------------------------------------------------------------------------
    if facts.connector_names:
        names = ", ".join(facts.connector_names)
        flows.append(
            DataFlow(
                id="connectors",
                title="Connectors you've granted this project",
                when="Whenever the agent uses one of their tools — only as far as each tool's permission (On / Ask / Off) allows.",
                where=f"The connector's own server: {names}.",
                sends=("The arguments the agent passes to the tool, and the connection credential you gave that connector.",),
                never=("A connector you haven't granted to this project is not reachable from it at all.",),
                caveat="Whatever a connector's tool returns comes back into the agent's context, and from there goes to your model provider like anything else the agent reads.",
            )
        )

    # --- the preview + the agent's own browser -------------------------------------------------------------
    flows.append(
        DataFlow(
            id="preview",
            title="Live Preview and the agent's browser",
            when="When you open Live Preview, and — if enabled on this server — when the agent checks its own work.",
            where="You see the preview through this app's servers, which forward to your workspace. The agent's browser runs on this app's server.",
            sends=(
                "Your browser's requests to the preview, forwarded to your workspace.",
                "The agent's browser loads pages from your workspace only; the only other hosts it can reach are a short list of font and script CDNs set by whoever runs this server.",
            ),
            never=(
                "The agent's browser cannot visit any other website, any address inside this app's own network, or follow a redirect to one.",
                "The workspace platform's access token is attached only to requests for your own preview and is not readable by the page.",
            ),
            caveat=None if facts.browser_available else (facts.browser_unavailable_reason or "The agent's browser is not available for this project right now."),
        )
    )

    # --- this app's own database --------------------------------------------------------------------------
    flows.append(
        DataFlow(
            id="harness_db",
            title="This app's database",
            when="Always: it is how the app remembers your projects and conversations.",
            where="Supabase, the database this app runs on.",
            sends=(
                "Your conversations with the agent, including what its tools returned (with preview-secret values masked), project memory, an audit log of what the agent did, and deploy logs.",
                "Your credentials, stored encrypted: your model API key, your GitHub token, and any secrets you add.",
            ),
            never=("Secret values are kept only in encrypted storage; the conversation and the audit log record them masked.",),
        )
    )
    return flows
