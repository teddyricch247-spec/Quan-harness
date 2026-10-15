"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Composer from "@/components/Composer";
import EmptyState from "@/components/EmptyState";
import { StatusDot } from "@/components/Drawer";
import ModelSheet from "@/components/ModelSheet";
import NewProjectSheet, { ProjectSource } from "@/components/NewProjectSheet";
import ResendVerification from "@/components/ResendVerification";
import { useShell } from "@/components/ShellContext";
import TabSwitch from "@/components/TabSwitch";
import TopBar from "@/components/TopBar";
import { ApiError, isStartOut, startProject, StartProjectInput } from "@/lib/api";
import { CHAT_ENABLED } from "@/lib/flags";
import { shortModel, timeAgo } from "@/lib/format";
import { saveHandoff } from "@/lib/handoff";
import { clearReturnTo, setReturnTo } from "@/lib/returnTo";
import { saveDraft, useDraft } from "@/lib/useDraft";
import { defaultLlm, useConnections } from "@/lib/useConnections";

/**
 * Phase Convert (C4, C5 Flow A–C): Code home. A composer, and under it the projects. The composer
 * here always means *new project* — there is no "is this a new project?" question anywhere. The
 * minimum a person does is type a prompt and press send; every answer the old four-step wizard
 * asked has a default (scratch repo, the account's default model key, no connectors, the default
 * GitHub connection) and is changed, if at all, through the + sheet or the model chip.
 */
export default function CodeHomePage() {
  const router = useRouter();
  const { projects, projectsError, refreshProjects, email } = useShell();
  const conn = useConnections();
  const { draft, setDraft, clearDraft, ready } = useDraft("code-home");

  const [source, setSource] = useState<ProjectSource>({ kind: "scratch" });
  const [connectorIds, setConnectorIds] = useState<string[]>([]);
  // null = nothing chosen: send no credential id and let the backend use the account default.
  const [llmCredentialId, setLlmCredentialId] = useState<string | null>(null);
  const [sheet, setSheet] = useState<"setup" | "model" | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  // Arriving here ends any "go back to where I came from" breadcrumb a connect page was using.
  useEffect(() => clearReturnTo(), []);

  const hasKey = conn.llm.length > 0;
  const noKey = conn.loaded && !hasKey;
  const chosenLlm = conn.llm.find((c) => c.id === llmCredentialId) ?? defaultLlm(conn.llm);
  const importing = sending && source.kind === "import";
  const importLabel = source.kind === "import" ? `Importing ${source.repo}…` : null;

  function goConnect(path: string) {
    // The draft is already in localStorage (useDraft writes on every keystroke), so all the
    // return trip needs is to remember where "back" should go.
    setReturnTo("/projects");
    router.push(path);
  }

  async function send() {
    if (sending) return;
    setError(null);
    setErrorCode(null);

    // No usable model key yet: the send button's job is to get one connected, not to fail.
    if (noKey) {
      goConnect("/connections/llm-providers");
      return;
    }

    const prompt = draft.trim();
    if (!prompt && source.kind !== "import") return; // only an import may be sent with nothing typed

    const input: StartProjectInput = { prompt: prompt || undefined, connector_ids: connectorIds };
    // Send nothing when the key in use IS the account default (the backend falls back to it, as the
    // agent loop does). If the account has keys but none flagged default, the backend has nothing to
    // fall back to — so name the one we are showing explicitly.
    const explicitLlmId = llmCredentialId ?? (chosenLlm && !chosenLlm.is_default ? chosenLlm.id : null);
    if (explicitLlmId) input.llm_credential_id = explicitLlmId;
    if (source.kind === "import") {
      input.mode = "import";
      input.github_repo = source.repo;
    } else if (source.kind === "create") {
      input.mode = "create_new_repo";
      input.new_repo_name = source.name;
      input.new_repo_private = source.isPrivate;
    } else {
      input.mode = "scratch";
    }

    setSending(true);
    try {
      const result = await startProject(input);
      const project = isStartOut(result) ? result.project : result;

      if (isStartOut(result)) {
        saveHandoff(project.id, {
          session_id: result.session_id,
          turn_status: result.turn.status,
          prompt,
          import_pull_error: project.import_pull_error ?? null,
        });
        // C4: if an import's pull failed the turn was held back — the typed prompt becomes the
        // workspace's draft instead of being sent into an empty workspace.
        if (result.turn.status === "not_started" && prompt) saveDraft(`project:${project.id}`, prompt);
      } else {
        saveHandoff(project.id, { import_pull_error: project.import_pull_error ?? null });
      }

      clearDraft();
      refreshProjects();
      router.push(`/projects/${project.id}`);
    } catch (e) {
      const err = e as ApiError;
      setSending(false);
      // Branch on the stable code, never on message text (C8.1). The draft is untouched.
      if (err.code === "llm_key_required") {
        goConnect("/connections/llm-providers");
        return;
      }
      setErrorCode(err.code ?? null);
      setError(err.message);
    }
  }

  const sourceChip =
    source.kind === "scratch" ? null : (
      <span className="inline-flex items-center gap-1 text-[13px] border border-line rounded-full pl-2.5 pr-1 py-0.5 bg-paper">
        <span className="mono">{source.kind === "import" ? source.repo : `new: ${source.name}`}</span>
        <button
          aria-label="Remove repository source"
          onClick={() => setSource({ kind: "scratch" })}
          className="w-5 h-5 grid place-items-center rounded-full hover:bg-soft"
        >
          ×
        </button>
      </span>
    );

  const placeholder =
    projects && projects.length === 0 ? "Describe what you want to build…" : "Start a new project — say what you want built";

  return (
    <>
      <TopBar center={CHAT_ENABLED ? <TabSwitch /> : undefined} title={CHAT_ENABLED ? undefined : "Code"} />

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 pb-4">
          {errorCode === "email_not_verified" && (
            <div className="border border-accent/40 bg-accent-soft text-accent text-sm rounded-xl px-3 py-2 mb-3" role="alert">
              {error} <ResendVerification email={email} />
            </div>
          )}
          {errorCode === "github_not_connected" && (
            <div className="border border-warn bg-warn-soft text-sm rounded-xl px-3 py-2 mb-3" role="alert">
              Connect GitHub first to import or create a repository.{" "}
              <Link href="/connections/github" onClick={() => setReturnTo("/projects")} className="underline">
                Open GitHub settings
              </Link>
            </div>
          )}
          {error && errorCode !== "email_not_verified" && errorCode !== "github_not_connected" && (
            <div className="border border-accent/40 bg-accent-soft text-accent text-sm rounded-xl px-3 py-2 mb-3" role="alert">
              {error}
            </div>
          )}
          {noKey && (
            <div className="border border-warn bg-warn-soft rounded-xl px-3 py-2.5 mb-3 text-sm flex items-start gap-3">
              <p className="flex-1">Connect a model key to start. It takes a minute — paste one key, then come back to your message.</p>
              <Link href="/connections/llm-providers" onClick={() => setReturnTo("/projects")} className="btn-default text-xs flex-none">
                Connect a key
              </Link>
            </div>
          )}
          {projectsError && <p className="text-sm text-accent mb-3">{projectsError}</p>}

          {projects === null && !projectsError && <p className="text-sm text-muted py-6">Loading…</p>}

          {projects !== null && projects.length === 0 && (
            <EmptyState title="Nothing here yet">
              Say what you want to build below and press send. Your first project is created for you — no setup first.
            </EmptyState>
          )}

          {projects !== null && projects.length > 0 && (
            <section aria-label="Your projects">
              <h2 className="text-xs text-muted px-1 pt-2 pb-2">Projects</h2>
              <ul className="bg-white border border-line rounded-xl overflow-hidden">
                {projects.map((p) => (
                  <li key={p.id} className="border-b border-line last:border-b-0">
                    <Link href={`/projects/${p.id}`} className="flex items-center gap-3 px-4 py-3 min-h-[56px] hover:bg-paper">
                      <span className="flex-1 min-w-0">
                        <span className="block truncate font-medium">{p.name}</span>
                        <span className="block truncate text-xs text-muted mono">{p.repo_full_name ?? "no repository"}</span>
                      </span>
                      <span className="text-xs text-muted flex-none">{timeAgo(p.last_activity_at ?? p.created_at)}</span>
                      <StatusDot status={p.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl flex-none">
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={send}
          placeholder={placeholder}
          disabled={!ready || sending}
          busyLabel={importing ? importLabel : null}
          allowEmptySend={source.kind === "import"}
          onPlus={() => setSheet("setup")}
          plusLabel="Project setup"
          modelLabel={chosenLlm ? shortModel(chosenLlm.model) : "Connect a model"}
          onModel={() => (noKey ? goConnect("/connections/llm-providers") : setSheet("model"))}
          chips={sourceChip}
          autoFocus
          sendLabel={noKey ? "Connect a model key" : "Create project and send"}
        />
      </div>

      <NewProjectSheet
        open={sheet === "setup"}
        onClose={() => setSheet(null)}
        source={source}
        onSource={setSource}
        githubCredentials={conn.github}
        connectors={conn.connectors}
        connectorIds={connectorIds}
        onConnectorIds={setConnectorIds}
        onLeaveToConnectGithub={() => setReturnTo("/projects")}
      />
      <ModelSheet
        open={sheet === "model"}
        onClose={() => setSheet(null)}
        credentials={conn.llm}
        selectedId={chosenLlm?.id ?? null}
        onPick={(id) => setLlmCredentialId(conn.llm.find((c) => c.id === id)?.is_default ? null : id)}
        note="The model for the project you’re about to create. You can change it later from inside the project."
        onLeaveToConnect={() => setReturnTo("/projects")}
      />
    </>
  );
}
