"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import ChatPane from "@/components/ChatPane";
import CheckpointsSheet from "@/components/CheckpointsSheet";
import DeploySheet from "@/components/DeploySheet";
import EmptyState from "@/components/EmptyState";
import { MoreIcon } from "@/components/icons";
import ModelSheet from "@/components/ModelSheet";
import PreviewTab from "@/components/PreviewTab";
import ProjectMenuSheet, { MenuAction } from "@/components/ProjectMenuSheet";
import ProjectPlusSheet from "@/components/ProjectPlusSheet";
import PullSheet from "@/components/PullSheet";
import PushSheet from "@/components/PushSheet";
import RenameSheet from "@/components/RenameSheet";
import SecretsSheet from "@/components/SecretsSheet";
import SessionsSheet from "@/components/SessionsSheet";
import { useShell } from "@/components/ShellContext";
import TopBar from "@/components/TopBar";
import { apiFetch, ApiError } from "@/lib/api";
import { shortModel } from "@/lib/format";
import { StartHandoff, takeHandoff } from "@/lib/handoff";
import type { Project, Session } from "@/lib/types";
import { defaultLlm, useConnections } from "@/lib/useConnections";
import { useDeployRuns } from "@/lib/useDeployRuns";
import { useSheet } from "@/lib/useSheet";

type SheetName = MenuAction | "menu" | "plus" | "model" | "retrypull";

/**
 * Phase Convert (C4, C7): the workspace. A header (title opens Sessions, ⋯ opens the project
 * menu), then Chat and Preview — a two-way switch below 900 px, side by side from 900 px up. Push,
 * Pull, Checkpoints, Deploy, Secrets and Sessions are sheets behind the ⋯ menu; Project settings
 * keeps its own page.
 *
 * Both panes stay mounted and are only hidden with CSS: the Preview iframe must not be torn down
 * when someone flips to Chat and back (PreviewPanel's own comment explains why a live preview
 * can't survive that).
 */
export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  // `key` makes moving between projects (drawer → another project) a fresh mount. Without it React
  // reuses this component and every piece of state below — the open session, the one-time
  // hand-off, an import warning, a failed first prompt — would carry over from the previous project.
  return <Workspace key={id} id={id} />;
}

function Workspace({ id }: { id: string }) {
  const shell = useShell();
  const conn = useConnections();
  const deploy = useDeployRuns(id);
  const sheet = useSheet<SheetName>();

  const [project, setProject] = useState<Project | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [tab, setTab] = useState<"chat" | "preview">("chat");

  // Read once from sessionStorage (see lib/handoff.ts). A ref, so React Strict Mode's second effect
  // run in development sees the same value instead of an already-emptied store.
  const handoffRef = useRef<StartHandoff | null | undefined>(undefined);
  // The chat pane owns the pending pictures; it hands the + sheet a way to open its file picker.
  const imagePickerRef = useRef<(() => void) | null>(null);
  const registerImagePicker = useCallback((open: (() => void) | null) => {
    imagePickerRef.current = open;
  }, []);
  const [failedFirstPrompt, setFailedFirstPrompt] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  const reloadProject = useCallback(() => {
    apiFetch<Project>(`/projects/${id}`)
      .then((p) => {
        setProject(p);
        setLoadError(null);
      })
      .catch((e: ApiError) => setLoadError(e));
  }, [id]);

  useEffect(reloadProject, [reloadProject]);

  // First load: the handoff from Code home, then the sessions (open the one just created, else the
  // most recently active one — C4: "a project opens its most recently active session").
  useEffect(() => {
    if (handoffRef.current === undefined) handoffRef.current = takeHandoff(id);
    const h = handoffRef.current;
    if (h?.turn_status === "failed" && h.prompt) setFailedFirstPrompt(h.prompt);
    if (h?.import_pull_error) setImportError(h.import_pull_error);

    apiFetch<Session[]>(`/projects/${id}/sessions`)
      .then((list) => {
        const live = list.filter((s) => s.status !== "archived");
        const preferred = h?.session_id ? live.find((s) => s.id === h.session_id) : undefined;
        const recent = [...live].sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))[0];
        setSession(preferred ?? recent ?? null);
      })
      .catch(() => {})
      .finally(() => setSessionsLoaded(true));
  }, [id]);

  // While provisioning is in flight, watch it so the setup card moves on its own (C8.5).
  useEffect(() => {
    if (project?.workspace_status !== "provisioning") return;
    const t = setInterval(reloadProject, 3000);
    return () => clearInterval(t);
  }, [project?.workspace_status, reloadProject]);

  const onActivity = useCallback(() => {
    reloadProject();
    shell.refreshProjects();
    shell.refreshAttention();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadProject, shell.refreshProjects, shell.refreshAttention]);

  async function retrySetup() {
    // Retry setup = the existing wake endpoint: ensure_workspace plus a no-op command.
    try {
      await apiFetch(`/projects/${id}/workspace/wake`, { method: "POST" });
      reloadProject();
    } catch (e) {
      setProject((p) => (p ? { ...p, workspace_status: "failed", workspace_error: (e as ApiError).message } : p));
    }
  }

  async function pickModel(credentialId: string) {
    try {
      setProject(await apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify({ llm_credential_id: credentialId }) }));
    } catch {
      // the sheet closes either way; the chip keeps showing what is actually saved
    }
  }

  if (loadError && !project) {
    return (
      <>
        <TopBar title="Project" />
        <EmptyState
          title={loadError.status === 404 ? "Project not found" : "Couldn’t load this project"}
          action={
            <Link href="/projects" className="btn-default">
              Back to projects
            </Link>
          }
        >
          {loadError.status === 404 ? "It may have been deleted." : loadError.message}
        </EmptyState>
      </>
    );
  }

  if (!project) {
    return (
      <>
        <TopBar title="Loading…" />
        <p className="p-4 text-sm text-muted">Loading…</p>
      </>
    );
  }

  const activeLlm = conn.llm.find((c) => c.id === project.llm_credential_id) ?? defaultLlm(conn.llm);
  const modelLabel = activeLlm ? shortModel(activeLlm.model) : conn.loaded ? "Connect a model" : null;

  const importBanner = importError ? (
    <div className="border border-warn bg-warn-soft rounded-xl p-3 text-sm" role="alert">
      <p className="mb-2">
        The repository is linked, but pulling its content into the workspace failed: <span className="mono break-words">{importError}</span>
        {failedFirstPrompt === null && " Your message was kept in the box below — send it once the pull works."}
      </p>
      <button className="btn-default" onClick={() => sheet.open("retrypull")}>
        Retry pull
      </button>
    </div>
  ) : null;

  const segment = (key: "chat" | "preview", label: string) => (
    <button
      onClick={() => setTab(key)}
      aria-pressed={tab === key}
      className={`flex-1 rounded-[7px] px-4 py-1.5 text-sm min-h-[32px] ${tab === key ? "bg-white font-semibold" : "text-muted"}`}
    >
      {label}
    </button>
  );

  return (
    <>
      <TopBar
        title={project.name}
        subtitle={project.repo_full_name ?? undefined}
        onTitleClick={() => sheet.open("sessions")}
        right={
          <button onClick={() => sheet.open("menu")} aria-label="Project menu" className="w-9 h-9 grid place-items-center rounded-lg border border-line bg-white">
            <MoreIcon />
          </button>
        }
      />

      <div className="flex-none px-3 pb-2 desk:hidden">
        <div className="flex bg-soft rounded-[9px] p-[3px] max-w-[260px]">
          {segment("chat", "Chat")}
          {segment("preview", "Preview")}
        </div>
      </div>

      <div className="flex-1 min-h-0 flex flex-col desk:grid desk:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <section className={`${tab === "chat" ? "flex" : "hidden"} desk:flex flex-col flex-1 min-h-0 desk:border-r desk:border-line`} aria-label="Chat">
          {sessionsLoaded ? (
            <ChatPane
              project={project}
              session={session}
              onSessionCreated={setSession}
              failedFirstPrompt={failedFirstPrompt}
              onFirstPromptRetried={() => setFailedFirstPrompt(null)}
              onActivity={onActivity}
              onRetrySetup={retrySetup}
              onPlus={() => sheet.open("plus")}
              modelLabel={modelLabel}
              onModel={() => sheet.open("model")}
              onOpenSessions={() => sheet.open("sessions")}
              registerImagePicker={registerImagePicker}
              banner={importBanner}
            />
          ) : (
            <p className="p-4 text-sm text-muted">Loading…</p>
          )}
        </section>

        <section className={`${tab === "preview" ? "flex" : "hidden"} desk:flex flex-col flex-1 min-h-0`} aria-label="Preview">
          <PreviewTab
            project={project}
            runs={deploy.runs}
            runsLoaded={deploy.loaded}
            onDeploy={() => sheet.open("deploy")}
            onOpenSecrets={() => sheet.open("secrets")}
          />
        </section>
      </div>

      <ProjectMenuSheet open={sheet.is("menu")} onClose={sheet.close} projectId={project.id} onSelect={(action) => sheet.open(action)} />
      <PushSheet open={sheet.is("push")} onClose={sheet.close} project={project} onDone={reloadProject} />
      <PullSheet open={sheet.is("pull")} onClose={sheet.close} project={project} onDone={reloadProject} />
      <PullSheet
        open={sheet.is("retrypull")}
        onClose={sheet.close}
        project={project}
        autoRun
        onDone={() => {
          setImportError(null);
          reloadProject();
        }}
      />
      <CheckpointsSheet open={sheet.is("checkpoints")} onClose={sheet.close} project={project} onDone={reloadProject} />
      <DeploySheet
        open={sheet.is("deploy")}
        onClose={sheet.close}
        project={project}
        runs={deploy.runs}
        onRunsChanged={deploy.startPolling}
        onProjectChanged={reloadProject}
      />
      <SecretsSheet open={sheet.is("secrets")} onClose={sheet.close} project={project} />
      <SessionsSheet
        open={sheet.is("sessions")}
        onClose={sheet.close}
        projectId={project.id}
        activeSessionId={session?.id ?? null}
        onSelect={(s) => {
          setSession(s);
          setTab("chat");
        }}
      />
      <RenameSheet
        open={sheet.is("rename")}
        onClose={sheet.close}
        project={project}
        onRenamed={(p) => {
          setProject(p);
          shell.refreshProjects();
        }}
      />
      <ProjectPlusSheet
        open={sheet.is("plus")}
        onClose={sheet.close}
        projectId={project.id}
        connectors={conn.connectors}
        onAddImage={() => {
          sheet.close();
          setTab("chat"); // the pictures wait in the chat pane's message box; make sure it is the visible one
          imagePickerRef.current?.(); // still inside the tap, so the browser allows the file picker
        }}
      />
      <ModelSheet
        open={sheet.is("model")}
        onClose={sheet.close}
        credentials={conn.llm}
        selectedId={activeLlm?.id ?? null}
        onPick={pickModel}
        note="Changes this project’s model for every session — the same setting as Project settings."
      />
    </>
  );
}
