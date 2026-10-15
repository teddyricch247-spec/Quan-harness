"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import {
  ACCEPT_ATTRIBUTE,
  MAX_IMAGES_PER_MESSAGE,
  PreparedImage,
  prepareImage,
  sendInterruptWithAttachments,
  sendMessageWithAttachments,
  uploadAttachment,
} from "@/lib/attachments";
import { openSessionStream } from "@/lib/stream";
import { agentHasStarted, buildRows, describeApproval, lastUserText, pendingApproval, Row, toolSummary } from "@/lib/transcript";
import type { Project, Session, SessionEvent } from "@/lib/types";
import { useDraft } from "@/lib/useDraft";
import AttachmentThumb from "./AttachmentThumb";
import Composer from "./Composer";
import { AlertIcon, CloseIcon, Spinner } from "./icons";
import SetupCard from "./SetupCard";

/**
 * The workspace's conversation pane: the streaming transcript, approval cards, the setup card, and
 * the composer.
 *
 * HAND-OFF NOTE. Phase Convert's spec calls this pane "unchanged" from Phase 6, but this repository
 * has no transcript UI — the project page rendered a "not built yet" placeholder where it goes. The
 * pane below is therefore a *new, deliberately plain* implementation against the existing backend
 * (GET /sessions/{id}, /stream, /messages, /interrupt, /approvals/{id}/resolve), written so that the
 * Convert flows work end to end. Its interface is the props below and nothing else; if the real
 * Phase 6 pane lives somewhere not in this repository, swap it in behind the same props.
 *
 * Streaming: lib/stream.ts (fetch-based, so it can send the Bearer token EventSource can't). The
 * server closes the stream itself on a terminal status (completed / failed / stuck /
 * waiting_approval), so a new turn — a message sent, an approval answered — reconnects from the last
 * event id seen. A dropped connection while a turn is running reconnects the same way.
 *
 * Pictures (Phase 6.1): the + sheet's "Add an image" opens a file picker (registerImagePicker hands the
 * page that opener). Each picture is shrunk and re-encoded in the browser at once (lib/attachments.ts) and waits
 * in the message box; on send it is uploaded to the session — created first if this is the project's first
 * message — and the message goes with the uploaded ids. Up to four per message.
 *
 * Not offered, because the backend has no endpoint for it: a Stop button (the loop can be steered
 * mid-run with /interrupt — which is what sending while running does — but not cancelled).
 */
export interface ChatPaneProps {
  project: Project;
  /** null until the first message is sent in a project that has no session yet. */
  session: Session | null;
  onSessionCreated: (session: Session) => void;
  /** The first turn could not be started by POST /projects (C4/C5 Flow B failure row). */
  failedFirstPrompt: string | null;
  onFirstPromptRetried: () => void;
  /** Called whenever the turn's state changes, so the shell's dots and the project list can refresh. */
  onActivity: () => void;
  onRetrySetup: () => Promise<void>;
  onPlus: () => void;
  modelLabel: string | null;
  onModel: () => void;
  onOpenSessions: () => void;
  /** Shown above the transcript — e.g. an import's failed first pull with its Retry. */
  banner?: React.ReactNode;
  /** Gives the page a function that opens the picture picker (null when the pane goes away). */
  registerImagePicker?: (open: (() => void) | null) => void;
}

/** A picture waiting in the message box. */
interface PendingImage {
  key: string;
  name: string;
  state: "preparing" | "ready" | "failed";
  prepared?: PreparedImage;
  error?: string;
  /** Set once uploaded, so a retry after a failed send doesn't upload it a second time. */
  uploaded?: { sessionId: string; id: string };
}

type Status = Session["status"] | null;

export default function ChatPane({
  project,
  session,
  onSessionCreated,
  failedFirstPrompt,
  onFirstPromptRetried,
  onActivity,
  onRetrySetup,
  onPlus,
  modelLabel,
  onModel,
  onOpenSessions,
  banner,
  registerImagePicker,
}: ChatPaneProps) {
  const sessionId = session?.id ?? null;
  const { draft, setDraft, clearDraft, ready } = useDraft(`project:${project.id}`);

  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [status, setStatus] = useState<Status>(session?.status ?? null);
  const [plan, setPlan] = useState<Session["plan"] | null>(session?.plan ?? null);
  const [readOnly, setReadOnly] = useState(Boolean(session?.read_only));
  const [readOnlyReason, setReadOnlyReason] = useState<Session["read_only_reason"]>(session?.read_only_reason ?? null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [answering, setAnswering] = useState<Record<string, "allow" | "deny">>({});
  const [retryingSetup, setRetryingSetup] = useState(false);
  const [pending, setPending] = useState<PendingImage[]>([]);
  const pendingRef = useRef<PendingImage[]>([]);
  pendingRef.current = pending;
  const fileInputRef = useRef<HTMLInputElement>(null);

  const lastIdRef = useRef<number | null>(null);
  const statusRef = useRef<Status>(status);
  statusRef.current = status;
  const closeRef = useRef<(() => void) | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activityRef = useRef(onActivity);
  activityRef.current = onActivity;
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    registerImagePicker?.(() => fileInputRef.current?.click());
    return () => registerImagePicker?.(null);
  }, [registerImagePicker]);

  // Free the browser's copies of any pictures still waiting when the pane goes away.
  useEffect(
    () => () => {
      for (const p of pendingRef.current) if (p.prepared) URL.revokeObjectURL(p.prepared.previewUrl);
    },
    []
  );

  const disconnect = useCallback(() => {
    closeRef.current?.();
    closeRef.current = null;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    reconnectTimer.current = null;
  }, []);

  const refreshSession = useCallback((id: string) => {
    apiFetch<Session>(`/sessions/${id}`)
      .then((s) => {
        setStatus(s.status);
        setPlan(s.plan);
        setReadOnly(s.read_only);
        setReadOnlyReason(s.read_only_reason);
      })
      .catch(() => {});
  }, []);

  const connect = useCallback(
    (id: string) => {
      disconnect();
      closeRef.current = openSessionStream(id, lastIdRef.current, {
        onEvent: (ev) => {
          lastIdRef.current = Math.max(lastIdRef.current ?? 0, ev.id);
          setEvents((prev) => (prev.some((e) => e.id === ev.id) ? prev : [...prev, ev]));
        },
        onStatus: (st) => {
          setStatus(st as Status);
          if (st !== "running") {
            refreshSession(id);
            activityRef.current();
          }
        },
        onClose: (reason) => {
          // A dropped connection mid-turn: pick the stream back up from the last event seen.
          if (reason === "error" && statusRef.current === "running") {
            reconnectTimer.current = setTimeout(() => connect(id), 3000);
          }
        },
      });
    },
    [disconnect, refreshSession]
  );

  // Switching session (or arriving at one): start clean, read its state, open its stream.
  useEffect(() => {
    disconnect();
    setEvents([]);
    lastIdRef.current = null;
    setSendError(null);
    setAnswering({});
    if (!sessionId) {
      setStatus(null);
      setPlan(null);
      setReadOnly(false);
      setReadOnlyReason(null);
      return;
    }
    setStatus(session?.status ?? null);
    setPlan(session?.plan ?? null);
    setReadOnly(Boolean(session?.read_only));
    setReadOnlyReason(session?.read_only_reason ?? null);
    refreshSession(sessionId);
    connect(sessionId);
    return disconnect;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const rows = useMemo(() => buildRows(events), [events]);
  const approval = useMemo(() => pendingApproval(rows), [rows]);
  const started = agentHasStarted(events);
  const running = status === "running";
  const turnLive = running || sending;
  const showSetup = !started && (events.length > 0 || running || sending || Boolean(failedFirstPrompt) || project.workspace_status === "failed");

  // Keep the newest content in view unless the person has scrolled up to read.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  }, [rows.length, status, approval?.id]);

  function onScroll() {
    const el = scrollRef.current;
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const created = await apiFetch<Session>(`/projects/${project.id}/sessions`, { method: "POST", body: JSON.stringify({}) });
    onSessionCreated(created);
    return created.id;
  }

  function addImages(files: FileList | null) {
    if (!files || files.length === 0) return;
    const room = MAX_IMAGES_PER_MESSAGE - pendingRef.current.filter((p) => p.state !== "failed").length;
    const chosen = Array.from(files).slice(0, Math.max(0, room));
    setSendError(chosen.length < files.length ? `At most ${MAX_IMAGES_PER_MESSAGE} images can be attached to one message.` : null);
    for (const file of chosen) {
      const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setPending((prev) => [...prev, { key, name: file.name, state: "preparing" }]);
      prepareImage(file).then(
        (prepared) => {
          if (!pendingRef.current.some((p) => p.key === key)) {
            URL.revokeObjectURL(prepared.previewUrl); // removed while it was being prepared
            return;
          }
          setPending((prev) => prev.map((p) => (p.key === key ? { ...p, state: "ready", prepared } : p)));
        },
        (e: unknown) =>
          setPending((prev) =>
            prev.map((p) => (p.key === key ? { ...p, state: "failed", error: e instanceof Error ? e.message : "That image couldn't be used." } : p))
          )
      );
    }
  }

  function removeImage(key: string) {
    const gone = pendingRef.current.find((p) => p.key === key);
    if (gone?.prepared) URL.revokeObjectURL(gone.prepared.previewUrl);
    setPending((prev) => prev.filter((p) => p.key !== key));
  }

  function clearImages() {
    for (const p of pendingRef.current) if (p.prepared) URL.revokeObjectURL(p.prepared.previewUrl);
    setPending([]);
  }

  async function sendText(text: string, images: PendingImage[] = []): Promise<boolean> {
    const trimmed = text.trim();
    if ((!trimmed && images.length === 0) || sending) return false;
    setSending(true);
    setSendError(null);
    let messageStep = false;
    try {
      const id = await ensureSession();
      // Sent while a turn is running → steer it (§16's interrupt); otherwise start a turn.
      const interrupt = statusRef.current === "running";
      if (images.length === 0) {
        await apiFetch(interrupt ? `/sessions/${id}/interrupt` : `/sessions/${id}/messages`, { method: "POST", body: JSON.stringify({ text: trimmed }) });
      } else {
        const ids: string[] = [];
        for (const img of images) {
          if (!img.prepared) continue;
          if (img.uploaded?.sessionId === id) {
            ids.push(img.uploaded.id);
            continue;
          }
          const meta = await uploadAttachment(id, img.prepared);
          ids.push(meta.id);
          setPending((prev) => prev.map((p) => (p.key === img.key ? { ...p, uploaded: { sessionId: id, id: meta.id } } : p)));
        }
        messageStep = true;
        await (interrupt ? sendInterruptWithAttachments : sendMessageWithAttachments)(id, trimmed, ids);
      }
      stickToBottom.current = true;
      setStatus("running");
      connect(id);
      activityRef.current();
      return true;
    } catch (e) {
      // A 422 from the message step means an uploaded picture can't be used any more (expired, or already sent):
      // forget the uploads so the next try uploads them again.
      if (messageStep && (e as ApiError).status === 422) setPending((prev) => prev.map((p) => ({ ...p, uploaded: undefined })));
      setSendError((e as ApiError).message);
      return false;
    } finally {
      setSending(false);
    }
  }

  async function send() {
    const images = pending.filter((p) => p.state === "ready");
    if (await sendText(draft, images)) {
      clearDraft();
      clearImages();
    }
  }

  async function retryFirstPrompt() {
    if (failedFirstPrompt && (await sendText(failedFirstPrompt))) onFirstPromptRetried();
  }

  async function retryLast() {
    const text = lastUserText(events);
    if (text) await sendText(text);
  }

  async function resolve(approvalId: string, approved: boolean) {
    setAnswering((a) => ({ ...a, [approvalId]: approved ? "allow" : "deny" }));
    setSendError(null);
    try {
      await apiFetch(`/approvals/${approvalId}/resolve`, { method: "POST", body: JSON.stringify({ approved }) });
      if (sessionId) {
        setStatus("running");
        connect(sessionId); // the loop resumes; the old stream closed at waiting_approval
      }
      activityRef.current();
    } catch (e) {
      setSendError((e as ApiError).message);
      setAnswering((a) => {
        const next = { ...a };
        delete next[approvalId];
        return next;
      });
    }
  }

  async function retrySetup() {
    setRetryingSetup(true);
    try {
      await onRetrySetup();
    } finally {
      setRetryingSetup(false);
    }
  }

  const planSteps = Array.isArray(plan) ? plan : [];
  const readyImages = pending.filter((p) => p.state === "ready");
  const imageChips =
    pending.length > 0
      ? pending.map((p) => (
          <span key={p.key} className="inline-flex items-center gap-1.5 text-[13px] border border-line rounded-full pl-1 pr-1 py-0.5 bg-paper max-w-[220px]" title={p.error ?? p.name}>
            {p.state === "ready" && p.prepared ? (
              <img src={p.prepared.previewUrl} alt="" className="w-6 h-6 rounded-full object-cover flex-none" />
            ) : p.state === "preparing" ? (
              <Spinner className="w-4 h-4 ml-1 flex-none" />
            ) : (
              <AlertIcon className="w-4 h-4 ml-1 flex-none text-accent" />
            )}
            <span className={`truncate ${p.state === "failed" ? "text-accent" : ""}`}>{p.state === "failed" ? p.error : p.name}</span>
            <button type="button" onClick={() => removeImage(p.key)} aria-label={`Remove ${p.name}`} className="w-5 h-5 grid place-items-center rounded-full flex-none">
              <CloseIcon className="w-3 h-3" />
            </button>
          </span>
        ))
      : undefined;
  const empty = rows.length === 0 && !showSetup && !failedFirstPrompt;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 min-h-0 overflow-y-auto px-3 desk:px-4 py-3 space-y-3" aria-live="polite">
        {banner}

        {empty && (
          <div className="text-center text-sm text-muted py-10 px-6">
            {sessionId ? "Nothing in this session yet. Say what you want done." : "Say what you want done in this project."}
          </div>
        )}

        {rows.map((row) => (
          <TranscriptRow
            key={row.id}
            row={row}
            answering={row.kind === "approval" ? answering[row.approvalId] : undefined}
            onResolve={resolve}
            onRetry={retryLast}
            canRetry={!turnLive}
            sessionId={sessionId}
          />
        ))}

        {showSetup && <SetupCard project={project} agentStarted={started} onRetrySetup={retrySetup} retrying={retryingSetup} />}

        {failedFirstPrompt && (
          <div className="border border-accent/40 bg-accent-soft rounded-xl p-3 text-sm" role="alert">
            <p className="text-accent mb-2">Your project was created, but the first message couldn’t be started.</p>
            <button className="btn-default" onClick={retryFirstPrompt} disabled={sending}>
              {sending ? "Retrying…" : "Retry"}
            </button>
          </div>
        )}

        {running && !approval && <p className="text-xs text-muted px-1">Working…</p>}
      </div>

      {planSteps.length > 0 && (
        <details className="mx-3 desk:mx-4 mb-2 border border-line rounded-xl bg-white px-3 py-2 text-sm flex-none">
          <summary className="cursor-pointer select-none">
            Plan · {planSteps.filter((s) => s.status === "done").length}/{planSteps.length}
          </summary>
          <ol className="mt-2 space-y-1 list-decimal list-inside">
            {planSteps.map((s, i) => (
              <li key={i} className={s.status === "done" ? "text-muted line-through" : s.status === "in_progress" ? "font-medium" : ""}>
                {s.step}
              </li>
            ))}
          </ol>
        </details>
      )}

      {sendError && (
        <p className="mx-3 desk:mx-4 mb-2 text-sm text-accent flex-none" role="alert">
          {sendError}
        </p>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        multiple
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
        onChange={(e) => {
          addImages(e.target.files);
          e.target.value = ""; // so choosing the same picture again still fires
        }}
      />

      {readOnly ? (
        <div className="mx-3 desk:mx-4 border border-line bg-white rounded-xl px-3 py-3 text-sm flex-none mb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {readOnlyReason === "checkpoint_restore"
            ? "This session is read-only — a checkpoint was restored from another session."
            : "This session is read-only — this project already has the maximum number of sessions working at once."}{" "}
          <button className="underline" onClick={onOpenSessions}>
            Open or start a session
          </button>
        </div>
      ) : (
        <Composer
          value={draft}
          onChange={setDraft}
          onSend={send}
          allowEmptySend={readyImages.length > 0}
          blockSend={pending.some((p) => p.state === "preparing")}
          chips={imageChips}
          placeholder={running ? "Steer the agent…" : "Message the agent…"}
          disabled={!ready || sending}
          onPlus={onPlus}
          plusLabel="This project"
          modelLabel={modelLabel}
          onModel={onModel}
          sendLabel={running ? "Send while the agent is working" : "Send"}
        />
      )}
    </div>
  );
}

function TranscriptRow({
  row,
  answering,
  onResolve,
  onRetry,
  canRetry,
  sessionId,
}: {
  row: Row;
  answering: "allow" | "deny" | undefined;
  onResolve: (approvalId: string, approved: boolean) => void;
  onRetry: () => void;
  canRetry: boolean;
  sessionId: string | null;
}) {
  switch (row.kind) {
    case "user":
      return (
        <div className="flex justify-end">
          <div className="max-w-[85%] bg-ink text-white rounded-2xl rounded-br-md px-3.5 py-2 whitespace-pre-wrap break-words">
            {sessionId && row.attachments.length > 0 && (
              <div className={`flex flex-wrap gap-1.5 ${row.text ? "mb-1.5" : ""}`}>
                {row.attachments.map((a) => (
                  <AttachmentThumb key={a.id} sessionId={sessionId} id={a.id} filename={a.filename} width={a.width} height={a.height} />
                ))}
              </div>
            )}
            {row.text}
            {row.interrupt && <span className="block text-[11px] opacity-70 mt-0.5">Sent while the agent was working</span>}
          </div>
        </div>
      );
    case "agent":
      return <div className="max-w-[92%] whitespace-pre-wrap break-words">{row.text}</div>;
    case "tool":
      return (
        <details className="border border-line bg-white rounded-xl text-sm">
          <summary className="cursor-pointer select-none px-3 py-2 flex items-center gap-2 min-h-[40px]">
            <span
              className={`inline-block w-2 h-2 rounded-full flex-none ${row.result === null ? "bg-warn" : row.result.ok ? "bg-ok" : "bg-brand"}`}
              role="img"
              aria-label={row.result === null ? "Running" : row.result.ok ? "Succeeded" : "Failed"}
            />
            <span className="mono text-xs truncate">{toolSummary(row.name, row.arguments)}</span>
          </summary>
          <div className="px-3 pb-3 space-y-2">
            <pre className="mono text-xs bg-paper rounded-lg p-2 overflow-x-auto max-h-40 overflow-y-auto">{JSON.stringify(row.arguments, null, 2)}</pre>
            {row.result && (
              <pre className="mono text-xs bg-neutral-900 text-neutral-100 rounded-lg p-2 overflow-x-auto max-h-56 overflow-y-auto whitespace-pre-wrap">
                {(row.result.error ?? row.result.content ?? "").slice(0, 4000) || "(no output)"}
              </pre>
            )}
          </div>
        </details>
      );
    case "approval": {
      const { title, detail } = describeApproval(row.actionType, row.payload);
      return (
        <div className="border border-warn bg-warn-soft rounded-xl p-3 text-sm" role="group" aria-label="Approval needed">
          <p className="font-semibold mb-1">{title}</p>
          {detail && <pre className="mono text-xs bg-white border border-line rounded-lg p-2 mb-2 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap">{detail}</pre>}
          {row.answered === null ? (
            <div className="flex gap-2">
              <button className="btn-primary" disabled={Boolean(answering)} onClick={() => onResolve(row.approvalId, true)}>
                {answering === "allow" ? "Allowing…" : "Allow"}
              </button>
              <button className="btn-default" disabled={Boolean(answering)} onClick={() => onResolve(row.approvalId, false)}>
                {answering === "deny" ? "Denying…" : "Deny"}
              </button>
            </div>
          ) : (
            <p className="text-xs text-muted">{row.answered ? "Allowed" : "Denied"}</p>
          )}
        </div>
      );
    }
    case "error":
      return (
        <div className="border border-accent/40 bg-accent-soft rounded-xl p-3 text-sm" role="alert">
          <p className="text-accent break-words">{row.text || "Something went wrong."}</p>
          {canRetry && (
            <button className="btn-default mt-2" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      );
    case "notice":
      return (
        <p className={`text-xs px-1 ${row.severity === "hard" ? "text-accent" : "text-muted"}`}>{row.text}</p>
      );
  }
}
