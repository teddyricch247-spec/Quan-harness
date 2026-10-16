'use client';

import React, { useState, useRef, useEffect, useMemo, useCallback, useId, memo } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useApp } from '../../context/AppContext';
import { ChatMessage, ChatMessageImage } from '../../types';
import { getSupabase } from '../../lib/supabase';
import {
  CHAT_IMAGE_MAX_PER_CONVERSATION,
  CHAT_IMAGE_MAX_PER_MESSAGE,
  ChatImageDraft,
  pictureFilesFrom,
  prepareChatImage,
  releaseChatImage,
} from '../../lib/images';
import {
  CHAT_FILE_MAX_PER_MESSAGE,
  ChatFileDraft,
  ShownFile,
  attachedFileChars,
  buildMessageContent,
  fileDoesNotFit,
  filesFrom,
  formatChars,
  isAttachableFile,
  parseMessageContent,
  prepareChatFile,
  unsupportedFileMessage,
} from '../../lib/textFiles';
import { buildPreviewDocument, isHtmlCode } from '../../lib/htmlPreview';
import { firstMessageKaelReads } from '../../lib/historyWindow';
import { VOICE_MAX_SECONDS, VOICE_MIN_MS, VoiceRecorder, isVoiceSupported, startVoiceRecording } from '../../lib/voice';
import { ROUTES, playgroundSessionPath } from '../../lib/routes';
import { CHAT_MESSAGE_MAX_CHARS, MODELS, ThinkingLevel, fetchChatImage, modelInfo, transcribeAudio } from '../../lib/api';
import {
  ArrowUp,
  Copy,
  Check,
  SlidersHorizontal,
  X,
  Lock,
  LogIn,
  Plus,
  MessageSquare,
  Trash2,
  Edit2,
  PanelLeftClose,
  PanelLeft,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  RotateCcw,
  ArrowDown,
  Paperclip,
  Loader2,
  FileText,
  Mic,
  Square,
  Eye,
} from 'lucide-react';

// A message can arrive mid-stream with an opening ``` that hasn't been
// closed yet. Left alone, a markdown parser treats those stray backticks
// as literal text until the closing fence shows up. Balancing the fence
// count before rendering makes the code box appear immediately while the
// response is still generating, matching ChatGPT / Gemini / Claude.
function balanceFences(content: string): string {
  const fenceCount = (content.match(/```/g) || []).length;
  return fenceCount % 2 === 1 ? `${content}\n\`\`\`` : content;
}

// Full-screen preview of HTML code from a reply, in a sandboxed iframe (see
// lib/htmlPreview.ts for why it is safe to run and what it cannot do).
const HtmlPreviewModal: React.FC<{ code: string; onClose: () => void }> = ({ code, onClose }) => {
  const doc = useMemo(() => buildPreviewDocument(code), [code]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-[100] flex flex-col bg-ink/60 sm:p-6" role="dialog" aria-modal="true" aria-label="HTML preview" onClick={onClose}>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">HTML preview</p>
            <p className="text-[11px] text-ink-2">Sandboxed. Don&apos;t enter passwords.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-full p-2 text-ink-2 hover:bg-line-soft hover:text-ink cursor-pointer"
            title="Close preview"
            aria-label="Close preview"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <iframe
          title="HTML preview"
          sandbox="allow-scripts"
          srcDoc={doc}
          referrerPolicy="no-referrer"
          className="min-h-0 w-full flex-1 border-0 bg-white"
        />
      </div>
    </div>,
    document.body
  );
};

const CodeBlock: React.FC<{ code: string; language: string; canPreview?: boolean }> = ({ code, language, canPreview = false }) => {
  const [copied, setCopied] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const closePreview = useCallback(() => setPreviewOpen(false), []);
  const showPreview = canPreview && isHtmlCode(language, code);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (insecure context or permission denied): stay on
      // "Copy" rather than claiming it worked.
    }
  };

  return (
    <div className="my-2 w-full max-w-full rounded-xl border border-ink-2/60 bg-ink overflow-hidden text-left shadow-none not-prose">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-ink-2/60 bg-ink/80">
        <span className="text-[10px] font-mono font-semibold text-ink-3 uppercase tracking-wider truncate">
          {language}
        </span>
        <div className="flex items-center gap-3 shrink-0">
          {showPreview && (
            <button
              type="button"
              onClick={() => setPreviewOpen(true)}
              className="flex items-center gap-1 text-[10px] font-mono text-ink-3 hover:text-white transition-colors cursor-pointer"
              title="Preview this HTML"
              aria-label="Preview this HTML"
            >
              <Eye className="h-3 w-3" />
              <span>Preview</span>
            </button>
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1 text-[10px] font-mono text-ink-3 hover:text-white transition-colors cursor-pointer"
            title="Copy code"
            aria-label="Copy code"
          >
            {copied ? (
              <>
                <Check className="h-3 w-3 text-steel-light" />
                <span className="text-steel-light">Copied</span>
              </>
            ) : (
              <>
                <Copy className="h-3 w-3" />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>
      <pre className="max-h-96 overflow-y-auto overflow-x-auto p-3 text-xs sm:text-[13px] leading-relaxed">
        <code className="font-mono text-line-soft whitespace-pre">{code}</code>
      </pre>
      {previewOpen && showPreview && <HtmlPreviewModal code={code} onClose={closePreview} />}
    </div>
  );
};

// Full markdown "compiler" for message bodies — headings, bold/italic/
// strikethrough, ordered & unordered (incl. nested) lists, blockquotes,
// links, inline code, tables, and horizontal rules, on top of the fenced
// code-block handling above. Used for both AI responses and user text so
// pasted markdown/code from either side renders the same way. `isUser`
// only swaps the color tokens so text stays legible on the blue bubble.
const MarkdownContent: React.FC<{ content: string; isUser: boolean; allowPreview?: boolean }> = ({ content, isUser, allowPreview = false }) => {
  const safeContent = useMemo(() => balanceFences(content), [content]);

  const linkClass = isUser
    ? 'underline decoration-white/60 text-white hover:decoration-white'
    : 'underline decoration-steel/60 text-steel-ink hover:text-ink';
  const inlineCodeClass = isUser
    ? 'rounded bg-black/15 px-1 py-0.5 font-mono text-[0.85em]'
    : 'rounded bg-line-soft px-1 py-0.5 font-mono text-[0.85em] text-ink';
  const quoteClass = isUser
    ? 'border-l-2 border-white/40 pl-3 my-2 italic text-white/85'
    : 'border-l-2 border-line pl-3 my-2 italic text-ink-2';
  const hrClass = isUser ? 'my-3 border-white/30' : 'my-3 border-line';
  const tableWrapClass = isUser
    ? 'my-2 overflow-x-auto rounded-2xl border border-white/25'
    : 'my-2 overflow-x-auto rounded-2xl border border-line';
  const cellBorderClass = isUser ? 'border-white/25' : 'border-line';

  // Memoised so the renderers keep their identity between renders: react-markdown
  // uses each one as a component type, and a new function every render would
  // remount every code block (losing "Copied" and closing an open preview).
  const components = useMemo<Components>(
    () => ({
          p: ({ children }) => <p className="whitespace-pre-wrap font-sans leading-relaxed my-1.5">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          del: ({ children }) => <del className="line-through opacity-75">{children}</del>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className={linkClass}>
              {children}
            </a>
          ),
          h1: ({ children }) => <h1 className="text-base font-bold mt-3 mb-1.5 first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-bold mt-3 mb-1.5 first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-2.5 mb-1 first:mt-0">{children}</h3>,
          h4: ({ children }) => <h4 className="text-sm font-semibold mt-2 mb-1 first:mt-0">{children}</h4>,
          h5: ({ children }) => <h5 className="text-sm font-semibold mt-2 mb-1 first:mt-0">{children}</h5>,
          h6: ({ children }) => (
            <h6 className="text-sm font-semibold uppercase tracking-wide mt-2 mb-1 first:mt-0">{children}</h6>
          ),
          ul: ({ children }) => <ul className="list-disc pl-5 my-1.5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 my-1.5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => <blockquote className={quoteClass}>{children}</blockquote>,
          hr: () => <hr className={hrClass} />,
          table: ({ children }) => (
            <div className={tableWrapClass}>
              <table className="w-full text-xs sm:text-[13px] border-collapse">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className={isUser ? 'bg-black/10' : 'bg-surface'}>{children}</thead>,
          th: ({ children }) => (
            <th className={`px-2 py-1 text-left font-semibold border-b ${cellBorderClass}`}>{children}</th>
          ),
          td: ({ children }) => <td className={`px-2 py-1 border-b ${cellBorderClass} align-top`}>{children}</td>,
          // Strip the default <pre> wrapper — CodeBlock below supplies its
          // own box, so letting <pre> pass through would double-wrap it.
          pre: ({ children }) => <>{children}</>,
          code: ({ className, children }) => {
            const match = /language-([\w+-]+)/.exec(className || '');
            const raw = String(children).replace(/\n$/, '');
            const isBlock = Boolean(match) || raw.includes('\n');
            if (isBlock) {
              return <CodeBlock code={raw} language={match ? match[1] : 'text'} canPreview={allowPreview} />;
            }
            return <code className={inlineCodeClass}>{children}</code>;
          },
    }),
    [isUser, allowPreview, linkClass, inlineCodeClass, quoteClass, hrClass, tableWrapClass, cellBorderClass]
  );

  return (
    <div className="space-y-1 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {safeContent}
      </ReactMarkdown>
    </div>
  );
};

// ChatGPT/Gemini-style collapse for long user messages: clamps to a
// compact box by default (rather than a long vertical strip) with a
// "Show more" toggle, so a big pasted block doesn't push the whole
// conversation down.
const USER_COLLAPSE_LINE_THRESHOLD = 8;
const USER_COLLAPSE_CHAR_THRESHOLD = 600;

const CollapsibleUserContent: React.FC<{ content: string }> = ({ content }) => {
  const [expanded, setExpanded] = useState(false);
  const isLong =
    content.split('\n').length > USER_COLLAPSE_LINE_THRESHOLD || content.length > USER_COLLAPSE_CHAR_THRESHOLD;

  if (!isLong) {
    return <MarkdownContent content={content} isUser />;
  }

  return (
    <div>
      <div className={`relative overflow-hidden ${expanded ? '' : 'max-h-32'}`}>
        <MarkdownContent content={content} isUser />
        {!expanded && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-steel to-transparent" />
        )}
      </div>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mt-1.5 flex items-center gap-1 text-xs font-semibold text-white/85 hover:text-white cursor-pointer"
      >
        {expanded ? (
          <>
            <ChevronUp className="h-3 w-3" /> Show less
          </>
        ) : (
          <>
            <ChevronDown className="h-3 w-3" /> Show more
          </>
        )}
      </button>
    </div>
  );
};

// Display name for the message label: a current model's name, else "Assistant"
// (a 'legacy' conversation, from a model that no longer exists).
const modelDisplayName = (model: string): string => modelInfo(model)?.name ?? 'Assistant';

// Titles stored before the "conversation" wording (and the empty title) show
// as "New conversation". The backend already maps these; this covers rows the
// client builds itself and a frontend that is deployed before its backend.
const DEFAULT_CONVERSATION_TITLE = 'New conversation';
const conversationTitle = (title?: string | null): string => {
  const t = (title ?? '').trim();
  return !t || /^(new chat|untitled chat|new session)$/i.test(t) ? DEFAULT_CONVERSATION_TITLE : t;
};

const SESSION_BUSY_TITLE = 'Wait for the current reply to finish';

// Pointer type decides keyboard behaviour: on a phone Enter is a newline (the
// send button is right there); with a mouse/keyboard Enter sends.
const isCoarsePointer = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;

// What Kael streamed as "thinking" for a reply: the same short titles the API
// sends as reasoning_content (not the raw reasoning, which Kael never exposes).
// Collapsed by default. While the answer has not started it doubles as the live
// status line (latest title, pulsing); once the reply is done it stays as a
// "Thinking · N steps" row that expands to the full list, and it is saved with
// the reply so it is still there after a reload.
const ThinkingBlock: React.FC<{ steps: string[]; live: boolean }> = ({ steps, live }) => {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const latest = steps[steps.length - 1];
  return (
    <div className={`w-fit max-w-full ${live ? 'mb-0' : 'mb-2'}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={listId}
        className="group flex max-w-full items-start gap-2 rounded-lg py-1 text-left text-sm text-ink-2 hover:text-ink cursor-pointer"
      >
        {live ? (
          <>
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-steel animate-pulse" aria-hidden="true" />
            <span className="min-w-0" role="status">
              {latest}
            </span>
          </>
        ) : (
          <span className="min-w-0 font-medium">
            Thinking <span className="font-normal text-ink-3">· {steps.length} {steps.length === 1 ? 'step' : 'steps'}</span>
          </span>
        )}
        <ChevronDown
          className={`mt-0.5 h-3.5 w-3.5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <ol
          id={listId}
          className="mt-1 mb-1 ml-1 max-h-72 space-y-1.5 overflow-y-auto border-l-2 border-line pl-3 text-[13px] leading-snug text-ink-2"
        >
          {steps.map((step, i) => (
            <li key={i} className="break-words">
              {step}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
};

// A file (text, code, PDF or Word) shown inside a sent message: its name and size,
// and a tap to read the text that was attached (so it can be checked after a reload).
const AttachedFileChip: React.FC<{ file: ShownFile }> = ({ file }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="max-w-full min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-white/15 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-white/25 transition-colors cursor-pointer"
      >
        <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="truncate">{file.name}</span>
        <span className="shrink-0 text-white/75">{formatChars(file.chars)}</span>
        {open ? <ChevronUp className="h-3 w-3 shrink-0" aria-hidden="true" /> : <ChevronDown className="h-3 w-3 shrink-0" aria-hidden="true" />}
      </button>
      {open && (
        <pre className="mt-1.5 max-h-60 overflow-auto rounded-lg bg-black/25 p-2.5 text-left text-[11px] leading-snug font-mono whitespace-pre-wrap break-words text-white/90">
          {file.text}
        </pre>
      )}
    </div>
  );
};

// One picture attached to a message. A picture attached in this page has its own
// local `src`. A picture loaded from a saved conversation only has an id: its
// bytes are fetched with the login token when it is shown (a picture is never
// reachable by URL alone) and released when it goes away. Click to see it large.
const AttachedImage: React.FC<{ image: ChatMessageImage; sessionId: string | null }> = ({ image, sessionId }) => {
  const [src, setSrc] = useState<string | null>(image.src ?? null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (image.src) {
      setSrc(image.src);
      return;
    }
    if (!image.id || !sessionId) return;
    let cancelled = false;
    let url: string | null = null;
    (async () => {
      try {
        const supabase = getSupabase();
        const auth = supabase ? await supabase.auth.getSession() : null;
        const token = auth?.data?.session?.access_token;
        if (!token) throw new Error('signed out');
        const blob = await fetchChatImage(token, sessionId, image.id as string);
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [image.src, image.id, sessionId]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [open]);

  if (failed) {
    return (
      <div className="flex h-24 w-24 sm:h-32 sm:w-32 items-center justify-center rounded-xl border border-white/30 bg-black/10 p-2 text-center text-[11px] leading-tight text-white/85">
        Picture unavailable
      </div>
    );
  }
  if (!src) {
    return <div className="h-24 w-24 sm:h-32 sm:w-32 rounded-xl bg-black/10 animate-pulse" aria-hidden="true" />;
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="block overflow-hidden rounded-xl border border-white/30 bg-black/10 cursor-zoom-in"
        aria-label="View attached picture"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="Attached picture" className="h-24 w-24 sm:h-32 sm:w-32 object-cover" />
      </button>
      {open && (
        <div
          className="fixed inset-0 z-[160] flex items-center justify-center bg-ink/80 p-4 backdrop-blur-xs"
          onClick={() => setOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Attached picture"
        >
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="absolute right-4 top-4 rounded-full bg-white/90 p-2 text-ink hover:bg-white cursor-pointer"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt="Attached picture"
            onClick={(e) => e.stopPropagation()}
            className="max-h-[90vh] max-w-[95vw] rounded-xl object-contain shadow-2xl"
          />
        </div>
      )}
    </>
  );
};

// Characters of attached-file text in a user message, remembered per message
// object (messages are replaced, not edited, and only the one being streamed
// changes while a reply is written, so this is parsed once per message).
const fileCharsByMessage = new WeakMap<ChatMessage, number>();
const messageFileChars = (m: ChatMessage): number => {
  let n = fileCharsByMessage.get(m);
  if (n === undefined) {
    n = m.role === 'user' ? attachedFileChars(m.content) : 0;
    fileCharsByMessage.set(m, n);
  }
  return n;
};

const formatClock = (seconds: number): string => {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
};

// A message can be resent from this page only if every picture it had is still
// in memory (attached here). One loaded from the server, or only known by count,
// would be resent without its pictures, so it is not offered a Retry.
const canResend = (msg: ChatMessage | undefined): boolean =>
  !!msg && msg.role === 'user' && !msg.imageCount && (msg.images ?? []).every((i) => !!i.data);

interface MessageRowProps {
  msg: ChatMessage;
  sessionId: string | null;
  isStreaming: boolean;
  canRetry: boolean;
  copied: boolean;
  onCopy: (text: string, id: string) => void;
  onRetry: (id: string) => void;
}

// One row. Memoised: while a reply streams, only the message that is being
// written changes identity, so the others (each a full markdown parse) are
// skipped instead of being re-rendered for every token.
const MessageRow = memo(function MessageRow({ msg, sessionId, isStreaming, canRetry, copied, onCopy, onRetry }: MessageRowProps) {
  const isUser = msg.role === 'user';
  // A user message may carry attached text files inside its text (see
  // lib/textFiles.ts). Show them as chips and show only what was typed as text.
  const parsed = useMemo(() => (isUser ? parseMessageContent(msg.content) : null), [isUser, msg.content]);
  const shownText = isUser ? (parsed?.text ?? msg.content) : msg.content;
  const displayName = isUser ? 'You' : modelDisplayName(msg.model);
  const hasSteps = !isUser && Array.isArray(msg.thinking) && msg.thinking.length > 0;
  if (!isUser && !msg.content && !msg.error && !isStreaming && !hasSteps) return null;

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`min-w-0 flex flex-col ${isUser ? 'items-end max-w-[85%] sm:max-w-xl' : 'items-start max-w-2xl w-full'}`}>
        <div
          className={`rounded-2xl p-3.5 sm:p-4 text-sm sm:text-[15px] leading-relaxed w-fit max-w-full ${
            isUser ? 'bg-steel text-white rounded-tr-xs shadow-none' : 'text-ink'
          }`}
        >
          {isUser && msg.images && msg.images.length > 0 && (
            <div className={`flex flex-wrap justify-end gap-2 ${msg.content ? 'mb-2' : ''}`}>
              {msg.images.map((image, i) => (
                <AttachedImage key={image.id ?? image.src ?? i} image={image} sessionId={sessionId} />
              ))}
            </div>
          )}
          {isUser && !msg.images?.length && !!msg.imageCount && (
            <div className={`text-xs font-medium text-white/85 ${msg.content ? 'mb-2' : ''}`}>
              {msg.imageCount === 1 ? '1 picture attached' : `${msg.imageCount} pictures attached`}
            </div>
          )}
          {isUser && parsed && parsed.files.length > 0 && (
            <div className={`flex flex-col items-end gap-1.5 ${shownText ? 'mb-2' : ''}`}>
              {parsed.files.map((file, i) => (
                <AttachedFileChip key={`${file.name}_${i}`} file={file} />
              ))}
            </div>
          )}
          {!isUser && hasSteps && <ThinkingBlock steps={msg.thinking!} live={isStreaming && !msg.content && !msg.error} />}
          {msg.content ? (
            isUser ? (shownText ? <CollapsibleUserContent content={shownText} /> : null) : <MarkdownContent content={msg.content} isUser={false} allowPreview={!isStreaming} />
          ) : isStreaming && !msg.error && !hasSteps ? (
            // Before the first answer token: the backend's own thinking
            // titles when it sends them (it streams a title every few
            // seconds, which this page used to drop), else a plain label.
            <div role="status" className="flex items-start gap-2 text-ink-2 text-sm">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-steel animate-pulse" aria-hidden="true" />
              <span className="min-w-0">{msg.thinkingLabel || 'Thinking…'}</span>
            </div>
          ) : null}

          {msg.error && (
            <div
              role="alert"
              className={`flex items-start gap-2 rounded-xl border border-danger-border bg-danger-soft px-3 py-2.5 text-xs sm:text-[13px] text-danger ${msg.content ? 'mt-2' : ''}`}
            >
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="leading-relaxed">{msg.error}</p>
                {canRetry && (
                  <button
                    type="button"
                    onClick={() => onRetry(msg.id)}
                    className="mt-1.5 inline-flex items-center gap-1 rounded-full border border-danger-border bg-white px-2.5 py-1 text-xs font-semibold text-danger hover:bg-danger-soft transition-colors cursor-pointer"
                  >
                    <RotateCcw className="h-3 w-3" aria-hidden="true" />
                    Retry
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="mt-1 flex items-center gap-2 px-1 text-[10px] text-ink-2 font-mono">
          <span className="font-semibold uppercase">{displayName}</span>
          {msg.timestamp && <span>{msg.timestamp}</span>}
          {!isUser && typeof msg.latencyMs === 'number' && msg.latencyMs > 0 && <span>{msg.latencyMs}ms</span>}
          {shownText && (
            <button
              type="button"
              onClick={() => onCopy(shownText, msg.id)}
              className="hover:text-ink p-1 -m-0.5 cursor-pointer"
              title="Copy"
              aria-label="Copy message"
            >
              {copied ? <Check className="h-3 w-3 text-steel" /> : <Copy className="h-3 w-3" />}
            </button>
          )}
        </div>
      </div>
    </div>
  );
});

const formatSessionTime = (isoString: string) => {
  if (!isoString) return '';
  try {
    const date = new Date(isoString);
    const diffMs = Date.now() - date.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
};

export const PlaygroundPage: React.FC = () => {
  const {
    chatMessages,
    sendChatMessage,
    retryChatMessage,
    setSelectedModel,
    activeModel,
    thinkingLevel,
    setThinkingLevel,
    isGenerating,
    isLoggedIn,
    authChecked,
    chatSessions,
    activeSessionId,
    isSessionsLoading,
    isSessionUnresumable,
    isSessionLoading,
    sessionsError,
    sessionLoadError,
    loadChatSessions,
    startNewChatSession,
    selectChatSession,
    renameChatSession,
    deleteChatSession,
  } = useApp();

  const router = useRouter();
  // /playground/[sessionId] — a normal dynamic segment. sessionId is
  // undefined on the bare /playground and a plain string on
  // /playground/<id>.
  const params = useParams<{ sessionId?: string }>();
  const routeSessionId = params?.sessionId ?? null;

  const [inputPrompt, setInputPrompt] = useState('');
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);
  const [wakingUp, setWakingUp] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showJump, setShowJump] = useState(false);

  // Inline editing / confirm state for the sidebar rows
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const [showSettings, setShowSettings] = useState(false);

  // Pictures being attached to the message in the box (shrunken and ready), how
  // many are still being prepared, and whether a file is being dragged over.
  const [drafts, setDrafts] = useState<ChatImageDraft[]>([]);
  const [preparing, setPreparing] = useState(0);
  const [dragOver, setDragOver] = useState(false);
  // Text and code files being attached (see lib/textFiles.ts).
  const [fileDrafts, setFileDrafts] = useState<ChatFileDraft[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Voice typing: the recording goes to the server as audio, comes back as text
  // and is put in the message box. Nothing but the text is ever sent to Kael.
  type VoiceState = 'idle' | 'starting' | 'recording' | 'transcribing';
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const [voiceSeconds, setVoiceSeconds] = useState(0);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recorderRef = useRef<VoiceRecorder | null>(null);
  const voiceBusyRef = useRef(false);
  const voiceAliveRef = useRef(true);
  useEffect(() => {
    voiceAliveRef.current = true;
    setVoiceSupported(isVoiceSupported());
    // Leaving the page mid-recording must not leave the microphone on.
    return () => {
      voiceAliveRef.current = false;
      recorderRef.current?.cancel();
    };
  }, []);
  // The drafts still in the box when the page goes away, to release their previews.
  const draftsRef = useRef<ChatImageDraft[]>([]);
  draftsRef.current = drafts;
  const fileDraftsRef = useRef<ChatFileDraft[]>([]);
  fileDraftsRef.current = fileDrafts;
  useEffect(() => () => draftsRef.current.forEach(releaseChatImage), []);

  // Attachments belong to the conversation they were added in. When another chat
  // is opened (or New chat is pressed), whatever was attached but not yet sent is
  // dropped, so it can never be sent into a different conversation by mistake.
  // Typed text stays. `attachEpochRef` also tells files that are still being read
  // that they arrived too late and must be discarded.
  const attachScopeRef = useRef<string | null>(activeSessionId);
  const attachEpochRef = useRef(0);
  useEffect(() => {
    if (attachScopeRef.current === activeSessionId) return;
    attachScopeRef.current = activeSessionId;
    attachEpochRef.current += 1;
    draftsRef.current.forEach(releaseChatImage);
    setDrafts([]);
    setFileDrafts([]);
  }, [activeSessionId]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // True while the reader is at (or near) the bottom: only then does new
  // content pull the view down, so scrolling up to read mid-reply sticks.
  const stickToBottomRef = useRef(true);

  const activeSession = chatSessions.find((s) => s.id === activeSessionId);
  // Conversations from a model that no longer exists are read-only: the backend
  // marks them resumable: false. Every other conversation shows its own model.
  const sessionLabel = (s: { model: string; resumable?: boolean }) =>
    s.resumable === false ? 'Legacy' : modelInfo(s.model)?.name ?? 'Legacy';
  const activeModelInfo = modelInfo(activeModel) ?? MODELS[0];
  const currentModelName = activeSession ? sessionLabel(activeSession) : activeModelInfo.name;
  // The model is chosen before the first message; after that the conversation is
  // locked to it (the backend will not continue it on the other one).
  const modelLocked = Boolean(activeSessionId);

  const lastMessage = chatMessages[chatMessages.length - 1];
  const awaitingFirstSignal =
    isGenerating && lastMessage?.role === 'assistant' && !lastMessage.content && !lastMessage.thinkingLabel && !lastMessage.error;

  // --- scrolling -----------------------------------------------------------
  // Scrolls the message container itself. The old code called
  // scrollIntoView() on a sentinel for every streamed token, which also
  // scrolls every ancestor (the page jumped) and fought manual scrolling.
  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  }, []);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    stickToBottomRef.current = nearBottom;
    setShowJump((prev) => (prev === !nearBottom ? prev : !nearBottom));
  };

  useEffect(() => {
    if (stickToBottomRef.current) scrollToBottom();
  }, [chatMessages, isSessionLoading, scrollToBottom]);

  // Opening a different chat always starts at its latest message.
  useEffect(() => {
    stickToBottomRef.current = true;
    scrollToBottom();
  }, [activeSessionId, scrollToBottom]);

  // Keep the loaded conversation in sync with the URL. This is the piece
  // that actually makes /playground/<sessionId> mean something: instead of
  // sidebar clicks calling selectChatSession() directly, they just
  // navigate, and this effect is the single place that reacts to whatever
  // the address bar currently says — covering sidebar clicks, "New Conversation",
  // browser back/forward, and a fresh tab landing straight on a session
  // link, all the same way.
  useEffect(() => {
    // Wait for the initial Supabase session check so a logged-in user
    // opening a session link directly doesn't get bounced through a
    // "please sign in" flash before their session even resolves.
    if (!authChecked) return;
    // Never yank the conversation out from under an in-flight send/stream
    // (e.g. sending the first message of a new conversation moves the URL to the
    // session it just created — that URL change shouldn't trigger a
    // competing fetch that clobbers the response still streaming in).
    if (isGenerating) return;
    // Already showing what the URL asks for — nothing to do.
    if (routeSessionId === activeSessionId) return;

    if (routeSessionId) {
      if (isLoggedIn) {
        selectChatSession(routeSessionId);
      }
      // Logged out: leave the current (welcome) messages as-is and let the
      // "sign in" banner below explain why nothing loaded, same as the
      // bare /playground already does for guests.
    } else {
      startNewChatSession();
    }
  }, [routeSessionId, activeSessionId, authChecked, isLoggedIn, isGenerating, selectChatSession, startNewChatSession]);

  // Reflect the open conversation in the browser tab. Auth is entirely
  // client-side (Supabase), so the server has no way to know a session's
  // title to set this itself — set it here once the client has it instead.
  useEffect(() => {
    document.title =
      activeSession && conversationTitle(activeSession.title) !== DEFAULT_CONVERSATION_TITLE
        ? `${conversationTitle(activeSession.title)} — Quancis`
        : 'Playground & Chat — Quancis';
  }, [activeSession?.title]);

  // Cold start notice (Render free tier): only while nothing at all has come
  // back yet. Once the backend streams a thinking title it is clearly awake.
  useEffect(() => {
    if (!awaitingFirstSignal) {
      setWakingUp(false);
      return;
    }
    const timer = setTimeout(() => setWakingUp(true), 10000);
    return () => clearTimeout(timer);
  }, [awaitingFirstSignal]);

  // Focus input when editing session title
  useEffect(() => {
    if (editingSessionId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [editingSessionId]);

  // Auto-grow the message box up to a cap.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [inputPrompt]);

  const canType = isLoggedIn && !isSessionUnresumable && !isSessionLoading;

  // Put the cursor back in the box when a reply finishes (and on first load
  // — the page remounts when the first message moves the URL to the new
  // chat) — desktop only, so a phone keyboard doesn't pop up unasked, and
  // never over something the user is already interacting with.
  useEffect(() => {
    if (!canType || isGenerating || isCoarsePointer()) return;
    const active = document.activeElement;
    if (active && active !== document.body && active !== textareaRef.current) return;
    textareaRef.current?.focus();
  }, [canType, isGenerating]);

  // Escape closes the settings modal first, then the sidebar drawer
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (showSettings) {
        setShowSettings(false);
      } else {
        setSidebarOpen(false);
        setConfirmDeleteId(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [showSettings]);

  // Rename/delete failures used to be console.warn only — the UI just did
  // nothing. They show in a banner now, then clear themselves.
  useEffect(() => {
    if (!actionError) return;
    const timer = setTimeout(() => setActionError(null), 7000);
    return () => clearTimeout(timer);
  }, [actionError]);

  // --- sending -------------------------------------------------------------
  const submitMessage = () => {
    const typed = inputPrompt.trim();
    // Text, pictures, files, or any mix; never nothing. Wait for attachments
    // still being prepared and for a recording to finish.
    if ((!typed && drafts.length === 0 && fileDrafts.length === 0) || isGenerating || !canType || preparing > 0 || voiceState !== 'idle') return;
    // Attached files travel inside the message text (lib/textFiles.ts), so the
    // limit on the whole message counts them too.
    const text = buildMessageContent(typed, fileDrafts);
    if (text.length > CHAT_MESSAGE_MAX_CHARS) {
      setActionError(
        `Your message and its files add up to ${text.length.toLocaleString()} characters; the limit is ${CHAT_MESSAGE_MAX_CHARS.toLocaleString()}. Shorten the message or remove a file.`
      );
      return;
    }
    const attached: ChatMessageImage[] = drafts.map((d) => ({ mime: d.mime, data: d.data, src: d.previewUrl }));
    setInputPrompt('');
    // The message now owns the previews (it shows them), so they are not released here.
    setDrafts([]);
    setFileDrafts([]);
    stickToBottomRef.current = true;
    sendChatMessage(text, attached);
  };

  // Pictures already in this conversation (sent here, or saved earlier): the
  // backend allows CHAT_IMAGE_MAX_PER_CONVERSATION in all.
  const conversationImageCount = chatMessages.reduce((n, m) => n + (m.images?.length ?? 0) + (m.imageCount ?? 0), 0);
  const imageSlotsLeft = Math.max(
    0,
    Math.min(
      CHAT_IMAGE_MAX_PER_MESSAGE - drafts.length - preparing,
      CHAT_IMAGE_MAX_PER_CONVERSATION - conversationImageCount - drafts.length - preparing
    )
  );
  // Where Kael's view of this conversation now starts (null: it sees all of it).
  const memoryStart = useMemo(() => firstMessageKaelReads(chatMessages), [chatMessages]);

  // Text and code files already attached in this conversation (their text is
  // resent every turn, so the backend caps it).
  // A message whose send failed (it is followed by an error reply) was never
  // saved, so its files do not count; Retry sends them again.
  const conversationFileChars = useMemo(
    () =>
      chatMessages.reduce((n, m, i) => {
        const next = chatMessages[i + 1];
        const failed = m.role === 'user' && next?.role === 'assistant' && !!next.error;
        return failed ? n : n + messageFileChars(m);
      }, 0),
    [chatMessages]
  );
  const fileSlotsLeft = Math.max(0, CHAT_FILE_MAX_PER_MESSAGE - fileDrafts.length);
  const canAttach = canType && !isGenerating && (imageSlotsLeft > 0 || fileSlotsLeft > 0);
  const attachTitle = !canType
    ? 'Attach'
    : isGenerating
      ? SESSION_BUSY_TITLE
      : canAttach
        ? 'Attach pictures, documents or code'
        : `Up to ${CHAT_IMAGE_MAX_PER_MESSAGE} pictures and ${CHAT_FILE_MAX_PER_MESSAGE} files per message`;

  const addFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || !canAttach) return;
      const room = imageSlotsLeft;
      const take = files.slice(0, room);
      if (files.length > room) {
        setActionError(
          room === 0
            ? `You can't attach more pictures here.`
            : drafts.length + preparing + files.length > CHAT_IMAGE_MAX_PER_MESSAGE
              ? `You can attach up to ${CHAT_IMAGE_MAX_PER_MESSAGE} pictures to one message. The first ${room} ${room === 1 ? 'was' : 'were'} added.`
              : `A conversation can hold up to ${CHAT_IMAGE_MAX_PER_CONVERSATION} pictures. The first ${room} ${room === 1 ? 'was' : 'were'} added.`
        );
      }
      setPreparing((n) => n + take.length);
      const epoch = attachEpochRef.current;
      await Promise.all(
        take.map(async (file) => {
          try {
            const draft = await prepareChatImage(file);
            if (attachEpochRef.current !== epoch) releaseChatImage(draft);
            else setDrafts((prev) => [...prev, draft]);
          } catch (err) {
            setActionError(err instanceof Error && err.message ? err.message : 'That picture could not be attached.');
          } finally {
            setPreparing((n) => n - 1);
          }
        })
      );
    },
    [canAttach, imageSlotsLeft, drafts.length, preparing]
  );

  // Text and code files: read one at a time so each is checked against the ones
  // already in the box and the ones already in the conversation.
  const addTextFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || !canAttach) return;
      let inBox = fileDraftsRef.current;
      setPreparing((n) => n + files.length);
      const epoch = attachEpochRef.current;
      for (const file of files) {
        try {
          const draft = await prepareChatFile(file);
          if (attachEpochRef.current !== epoch) continue; // another chat was opened meanwhile
          const problem = fileDoesNotFit(inBox, conversationFileChars, draft);
          if (problem) {
            setActionError(problem);
          } else {
            inBox = [...inBox, draft];
            setFileDrafts((prev) => [...prev, draft]);
          }
        } catch (err) {
          setActionError(err instanceof Error && err.message ? err.message : 'That file could not be attached.');
        } finally {
          setPreparing((n) => n - 1);
        }
      }
    },
    [canAttach, conversationFileChars]
  );

  // Whatever was picked, pasted or dropped: pictures take the picture path, text
  // and code files the file path, anything else is turned away with a reason.
  const addAttachments = (files: File[]) => {
    const pictures = pictureFilesFrom(files);
    const pictureSet = new Set(pictures);
    const others = files.filter((f) => !pictureSet.has(f));
    const texts = others.filter(isAttachableFile);
    const rejected = others.filter((f) => !isAttachableFile(f));
    if (rejected.length > 0) setActionError(unsupportedFileMessage(rejected[0]));
    if (pictures.length > 0) void addFiles(pictures);
    if (texts.length > 0) void addTextFiles(texts);
  };

  // --- voice typing ---------------------------------------------------------
  // What was said goes at the end of the box (after a space when there is text
  // already), where it can be edited like anything typed, and is sent only if
  // the user sends it.
  const insertTranscript = (spoken: string) => {
    const current = textareaRef.current?.value ?? '';
    const sep = current && !/\s$/.test(current) ? ' ' : '';
    const room = CHAT_MESSAGE_MAX_CHARS - current.length - sep.length;
    if (room <= 0) {
      setActionError('The message box is full, so the recording was not added.');
      return;
    }
    if (spoken.length > room) setActionError('Only the first part of the recording fit in the message box.');
    setInputPrompt((prev) => prev + (prev && !/\s$/.test(prev) ? ' ' : '') + spoken.slice(0, room));
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  };

  // Ends the recording (a tap on stop, or the time limit) and turns it into text.
  const finishVoice = async () => {
    const recorder = recorderRef.current;
    if (!recorder || voiceBusyRef.current) return;
    voiceBusyRef.current = true;
    recorderRef.current = null;
    setVoiceState('transcribing');
    try {
      const clip = await recorder.stop();
      if (clip.durationMs < VOICE_MIN_MS) {
        setActionError('Too short. Tap the microphone, speak, then tap again.');
        return;
      }
      if (!clip.heardSpeech) {
        setActionError("I didn't hear anything. Check your microphone and try again.");
        return;
      }
      const supabase = getSupabase();
      const auth = supabase ? await supabase.auth.getSession() : null;
      const token = auth?.data?.session?.access_token;
      if (!token) throw new Error('Please sign in again to use voice typing.');
      const spoken = await transcribeAudio(token, clip.blob);
      if (!spoken.trim()) {
        setActionError("Couldn't make out any words. Try again.");
        return;
      }
      if (voiceAliveRef.current) insertTranscript(spoken);
    } catch (err) {
      if (voiceAliveRef.current) setActionError(err instanceof Error && err.message ? err.message : 'Voice typing failed. You can still type your message.');
    } finally {
      voiceBusyRef.current = false;
      if (voiceAliveRef.current) setVoiceState('idle');
    }
  };

  const startVoice = async () => {
    if (voiceState !== 'idle' || voiceBusyRef.current || !canType) return;
    setActionError(null);
    setVoiceState('starting');
    try {
      const recorder = await startVoiceRecording({
        onTick: setVoiceSeconds,
        onLimit: () => {
          void finishVoice();
        },
      });
      if (!voiceAliveRef.current) {
        recorder.cancel();
        return;
      }
      recorderRef.current = recorder;
      setVoiceSeconds(0);
      setVoiceState('recording');
    } catch (err) {
      setVoiceState('idle');
      setActionError(err instanceof Error && err.message ? err.message : "Couldn't start recording. Please try again.");
    }
  };

  const cancelVoice = () => {
    recorderRef.current?.cancel();
    recorderRef.current = null;
    setVoiceState('idle');
  };

  const removeFileDraft = (key: string) => setFileDrafts((prev) => prev.filter((d) => d.key !== key));

  const removeDraft = (key: string) => {
    setDrafts((prev) => {
      const gone = prev.find((d) => d.key === key);
      if (gone) releaseChatImage(gone);
      return prev.filter((d) => d.key !== key);
    });
  };

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = filesFrom(e.target.files);
    e.target.value = ''; // so choosing the same file again fires change again
    if (picked.length === 0) return;
    addAttachments(picked);
  };

  // Pasting a screenshot, a copied picture or a copied file attaches it; pasting
  // text is unchanged.
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = filesFrom(e.clipboardData?.files);
    // Only take over the paste when something in it can be attached; anything
    // else (rich text that also lists a file, say) pastes as usual.
    if (!pasted.some((f) => pictureFilesFrom([f]).length > 0 || isAttachableFile(f))) return;
    e.preventDefault();
    addAttachments(pasted);
  };

  const hasFiles = (e: React.DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
  const handleDragOver = (e: React.DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (canAttach) setDragOver(true);
  };
  const handleDragLeave = (e: React.DragEvent) => {
    // Only when leaving the box itself, not when moving between its children.
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false);
  };
  const handleDrop = (e: React.DragEvent) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    setDragOver(false);
    const dropped = filesFrom(e.dataTransfer.files);
    if (dropped.length === 0) return;
    addAttachments(dropped);
  };

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    submitMessage();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter is a newline; never send mid-IME composition.
    if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing || isCoarsePointer()) return;
    e.preventDefault();
    submitMessage();
  };

  const copyMessageContent = useCallback(async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedMsgId(id);
      setTimeout(() => setCopiedMsgId((cur) => (cur === id ? null : cur)), 2000);
    } catch {
      // Clipboard blocked: leave the icon as is instead of showing a false check.
    }
  }, []);

  // retryChatMessage is recreated on every render of the provider; read it
  // through a ref so MessageRow's props stay stable and memo keeps working.
  const retryRef = useRef(retryChatMessage);
  retryRef.current = retryChatMessage;
  const handleRetry = useCallback((id: string) => {
    stickToBottomRef.current = true;
    retryRef.current(id);
  }, []);

  // --- sidebar actions -----------------------------------------------------
  const handleStartRename = (id: string, currentTitle: string) => {
    setConfirmDeleteId(null);
    setEditingSessionId(id);
    setEditingTitle(currentTitle);
  };

  const handleSaveRename = async (id: string, currentTitle: string) => {
    const next = editingTitle.trim();
    setEditingSessionId(null);
    setEditingTitle('');
    if (!next || next === currentTitle) return;
    const err = await renameChatSession(id, next);
    if (err) setActionError(err);
  };

  const handleConfirmDelete = async (id: string) => {
    setConfirmDeleteId(null);
    const err = await deleteChatSession(id);
    if (err) setActionError(err);
  };

  const handleNewChat = () => {
    if (isGenerating) return;
    setSidebarOpen(false);
    if (routeSessionId === null) {
      // Already on the bare playground — nothing for the URL-sync effect
      // to react to, so reset in place instead of a no-op navigation.
      startNewChatSession();
    } else {
      router.push(ROUTES.playground);
    }
  };

  const handleSelectSession = (sessionId: string) => {
    if (isGenerating) return;
    setSidebarOpen(false);
    if (sessionId !== routeSessionId) {
      router.push(playgroundSessionPath(sessionId));
    }
  };

  const placeholder = !isLoggedIn
    ? 'Sign in to start a conversation with Kael'
    : isSessionUnresumable
      ? 'This conversation is read-only. Start a new conversation to continue.'
      : isSessionLoading
        ? 'Loading conversation…'
        : 'Message Kael';

  const nearLimit = inputPrompt.length > CHAT_MESSAGE_MAX_CHARS * 0.9;

  return (
    <div className="h-full min-h-0 flex bg-surface relative overflow-hidden">
      {/* Sidebar backdrop — only exists while the drawer is open, and only
          dims the chat area (not the navbar above it) */}
      {sidebarOpen && (
        <div
          className="absolute inset-0 z-30 bg-ink/40 backdrop-blur-xs transition-opacity"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sessions Sidebar — always an overlay drawer that slides on top of
          the chat, never resizes/squeezes the chat area underneath it.
          `inert` while closed: off-screen buttons must not be reachable by
          Tab or by a screen reader. */}
      <aside
        aria-label="Conversations"
        inert={!sidebarOpen}
        className={`absolute inset-y-0 left-0 z-40 w-72 sm:w-80 bg-white border-r border-line flex flex-col shadow-2xl transition-transform duration-300 ease-out ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-3.5 border-b border-line-soft flex items-center justify-between gap-2">
          <button
            type="button"
            id="new-chat-btn"
            onClick={handleNewChat}
            disabled={isGenerating}
            title={isGenerating ? SESSION_BUSY_TITLE : undefined}
            className="flex-1 flex items-center justify-center gap-2 rounded-xl bg-black hover:bg-ink text-white px-3 py-2 text-xs font-semibold shadow-none transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus className="h-4 w-4" />
            <span>New Conversation</span>
          </button>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="rounded-2xl p-2 text-ink-2 hover:bg-line-soft hover:text-ink cursor-pointer"
            title="Close sidebar"
            aria-label="Close sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        </div>

        {sessionsError && (
          <div className="mx-3 mt-2 flex items-center justify-between gap-2 rounded-lg bg-warning-soft border border-warning-border px-2.5 py-1.5 text-[11px] text-warning">
            <span>Couldn&apos;t refresh your conversations.</span>
            <button type="button" onClick={() => loadChatSessions()} className="font-semibold underline underline-offset-2 cursor-pointer shrink-0">
              Retry
            </button>
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto py-2">
          {isSessionsLoading && chatSessions.length === 0 ? (
            <div className="p-4 text-center text-xs text-ink-2 font-mono">Loading conversations...</div>
          ) : chatSessions.length === 0 ? (
            <div className="p-6 text-center text-xs text-ink-2">
              <MessageSquare className="h-8 w-8 mx-auto mb-2 text-line" />
              <p className="font-medium text-ink-2">{sessionsError ? 'Conversations unavailable' : 'No conversations yet'}</p>
              <p className="text-[11px] text-ink-2 mt-1">
                {sessionsError ? 'Try again in a moment.' : 'Start a conversation to save it here.'}
              </p>
            </div>
          ) : (
            chatSessions.map((session) => {
              const isActive = session.id === activeSessionId;
              const isEditing = editingSessionId === session.id;
              const isConfirming = confirmDeleteId === session.id;
              const locked = isGenerating;
              const label = sessionLabel(session);

              return (
                <div
                  key={session.id}
                  className={`session-row group relative flex items-center gap-1 pr-2 transition-colors ${
                    isActive ? 'bg-steel-soft text-ink' : 'hover:bg-surface text-ink-2'
                  }`}
                >
                  {isEditing ? (
                    <div className="flex flex-1 items-center gap-1 pl-4 py-2">
                      <input
                        ref={renameInputRef}
                        type="text"
                        value={editingTitle}
                        maxLength={200}
                        aria-label="Conversation title"
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSaveRename(session.id, session.title);
                          if (e.key === 'Escape') {
                            e.stopPropagation();
                            setEditingSessionId(null);
                          }
                        }}
                        className="w-full min-w-0 text-base sm:text-xs font-semibold rounded px-1.5 py-0.5 border border-steel bg-white text-ink focus:outline-none"
                      />
                      <button
                        type="button"
                        onClick={() => handleSaveRename(session.id, session.title)}
                        className="p-1.5 text-steel-ink hover:text-ink cursor-pointer"
                        aria-label="Save title"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingSessionId(null)}
                        className="p-1.5 text-ink-2 hover:text-ink cursor-pointer"
                        aria-label="Cancel rename"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ) : isConfirming ? (
                    <div className="flex flex-1 items-center justify-between gap-2 pl-4 py-2.5 text-xs" role="alert">
                      <span className="font-semibold text-ink truncate">Delete this conversation?</span>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleConfirmDelete(session.id)}
                          className="rounded-full bg-danger px-2.5 py-1 text-[11px] font-semibold text-white hover:opacity-90 cursor-pointer"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-ink-2 hover:text-ink cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => handleSelectSession(session.id)}
                        disabled={locked && !isActive}
                        title={locked && !isActive ? SESSION_BUSY_TITLE : undefined}
                        aria-current={isActive ? 'page' : undefined}
                        className="flex-1 min-w-0 text-left pl-4 pr-1 py-2.5 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <span className="flex items-center gap-2">
                          <span className={`text-xs truncate ${isActive ? 'text-ink font-bold' : 'text-ink font-semibold'}`}>
                            {conversationTitle(session.title)}
                          </span>
                          <span className="shrink-0 text-[10px] text-ink-2 font-mono">
                            {formatSessionTime(session.last_message_at || session.created_at)} · {label}
                          </span>
                        </span>
                      </button>
                      <div className="session-actions flex items-center gap-0.5 shrink-0">
                        <button
                          type="button"
                          onClick={() => handleStartRename(session.id, session.title)}
                          className="p-1.5 rounded text-ink-2 hover:text-ink hover:bg-line/60 cursor-pointer"
                          title="Rename conversation"
                          aria-label={`Rename ${conversationTitle(session.title)}`}
                        >
                          <Edit2 className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(session.id)}
                          disabled={locked && isActive}
                          className="p-1.5 rounded text-ink-2 hover:text-danger hover:bg-danger-soft cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                          title={locked && isActive ? SESSION_BUSY_TITLE : 'Delete conversation'}
                          aria-label={`Delete ${conversationTitle(session.title)}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* Floating sidebar toggle — floats alone, does not live inside any
          header bar. Only shown while the drawer is closed; the drawer's
          own header has the close button. */}
      {!sidebarOpen && (
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="absolute top-3 left-3 z-20 rounded-full bg-white border border-line shadow-md p-2.5 text-ink-2 hover:bg-surface hover:text-ink transition-colors cursor-pointer"
          title="Open conversations"
          aria-label="Open conversations"
        >
          <PanelLeft className="h-4 w-4" />
        </button>
      )}

      {/* Main Chat View Area — always full width, never resized by the sidebar */}
      <div className="flex-1 min-w-0 flex flex-col h-full relative overflow-hidden">
        {isSessionUnresumable && (
          <div className="bg-warning-soft border-b border-warning-border pl-14 pr-4 py-2.5 text-xs text-warning flex items-center justify-between gap-2 shrink-0">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-warning shrink-0" />
              <span>This conversation was created with an option that is no longer available. You can read it, but not continue it.</span>
            </div>
            <button
              type="button"
              onClick={handleNewChat}
              disabled={isGenerating}
              className="rounded-2xl bg-warning-border/80 hover:bg-warning-border px-2.5 py-1 text-[11px] font-semibold text-warning transition-colors shrink-0 cursor-pointer"
            >
              Start New Conversation
            </button>
          </div>
        )}

        {/* Session Not Found / Load Error Banner — shown when the URL
            points at a session id that doesn't exist, isn't ours, or
            failed to load, so the address bar and what's on screen never
            silently disagree. */}
        {sessionLoadError && !isSessionUnresumable && (
          <div className="bg-danger-soft border-b border-danger-border pl-14 pr-4 py-2.5 text-xs text-danger flex items-center justify-between gap-2 shrink-0" role="alert">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 text-danger shrink-0" />
              <span>{sessionLoadError}</span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {/* A transient failure can be retried; "doesn't exist" can't. */}
              {routeSessionId && sessionLoadError.startsWith("Couldn't") && (
                <button
                  type="button"
                  onClick={() => selectChatSession(routeSessionId)}
                  className="rounded-2xl bg-danger-border/80 hover:bg-danger-border px-2.5 py-1 text-[11px] font-semibold text-danger transition-colors cursor-pointer"
                >
                  Try again
                </button>
              )}
              <button
                type="button"
                onClick={handleNewChat}
                disabled={isGenerating}
                className="rounded-2xl bg-danger-border/80 hover:bg-danger-border px-2.5 py-1 text-[11px] font-semibold text-danger transition-colors cursor-pointer"
              >
                Start New Conversation
              </button>
            </div>
          </div>
        )}

        {actionError && (
          <div className="bg-danger-soft border-b border-danger-border pl-14 pr-3 py-2 text-xs text-danger flex items-center justify-between gap-2 shrink-0" role="alert">
            <span>{actionError}</span>
            <button type="button" onClick={() => setActionError(null)} className="p-1 cursor-pointer" aria-label="Dismiss">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        {/* Messages — top padding clears the floating sidebar toggle */}
        <div className="relative flex-1 min-h-0">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            aria-label="Conversation"
            aria-busy={isSessionLoading}
            className="h-full overflow-y-auto overscroll-contain p-3 sm:p-6 lg:p-8 pt-14 space-y-4 max-w-5xl mx-auto w-full"
          >
            {isSessionLoading ? (
              <div className="space-y-4" aria-hidden="true">
                {[70, 45, 85].map((w, i) => (
                  <div key={i} className={`flex ${i % 2 === 0 ? 'justify-end' : 'justify-start'}`}>
                    <div className="h-12 rounded-2xl bg-line-soft animate-pulse" style={{ width: `${w}%`, maxWidth: '28rem' }} />
                  </div>
                ))}
              </div>
            ) : (
              chatMessages.map((msg: ChatMessage, idx) => (
                <React.Fragment key={msg.id}>
                  {idx === memoryStart && (
                    <div
                      role="separator"
                      title="Kael reads a conversation up to a size limit. The messages above this line are no longer included."
                      className="flex items-center gap-3 py-1 text-[11px] text-ink-3"
                    >
                      <span className="h-px flex-1 bg-line" />
                      <span>Kael no longer sees above this line</span>
                      <span className="h-px flex-1 bg-line" />
                    </div>
                  )}
                  <MessageRow
                    msg={msg}
                    sessionId={activeSessionId}
                    isStreaming={isGenerating && idx === chatMessages.length - 1 && msg.role === 'assistant'}
                    canRetry={!isGenerating && idx === chatMessages.length - 1 && canResend(chatMessages[idx - 1])}
                    copied={copiedMsgId === msg.id}
                    onCopy={copyMessageContent}
                    onRetry={handleRetry}
                  />
                </React.Fragment>
              ))
            )}

            {/* Cold Start / Waking Up Notice */}
            {wakingUp && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-tl-xs border border-warning-border bg-warning-soft/90 px-4 py-3 text-xs text-warning shadow-none flex items-center gap-2.5 font-mono" role="status">
                  <span className="h-2 w-2 rounded-full bg-warning animate-ping shrink-0" />
                  <span>Still working — the server may be waking up...</span>
                </div>
              </div>
            )}
          </div>

          {showJump && (
            <button
              type="button"
              onClick={() => {
                stickToBottomRef.current = true;
                scrollToBottom(true);
              }}
              className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 rounded-full border border-line bg-white px-3 py-1.5 text-xs font-semibold text-ink-2 shadow-md hover:text-ink cursor-pointer"
            >
              <ArrowDown className="h-3.5 w-3.5" />
              Latest
            </button>
          )}
        </div>

        {/* Message Box. Pictures and text files can be dropped anywhere on it. */}
        <div
          className="relative max-w-4xl mx-auto w-full px-3 sm:px-6 pb-3 sm:pb-4 pt-2 shrink-0"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {dragOver && (
            <div className="pointer-events-none absolute inset-x-3 sm:inset-x-6 inset-y-1 z-10 flex items-center justify-center rounded-3xl border-2 border-dashed border-steel bg-steel-soft/90 text-sm font-semibold text-steel-ink">
              Drop to attach
            </div>
          )}
          {!isLoggedIn && (
            <div className="mb-2 flex items-center justify-between gap-2 rounded-xl bg-warning-soft border border-warning-border/80 px-3 py-2 text-xs text-warning">
              <div className="flex items-center gap-2">
                <Lock className="h-3.5 w-3.5 text-warning shrink-0" />
                <span>Sign in to try Kael in the Playground.</span>
              </div>
              {/* Goes to the real sign-in page. The old button called
                  signInWithGitHub(false) directly, which skipped the Terms
                  checkbox and legal_acceptances record and left email and
                  Google users with no way in from here. */}
              <Link
                href={ROUTES.login}
                className="font-medium text-warning underline underline-offset-2 flex items-center gap-1 cursor-pointer shrink-0"
              >
                <LogIn className="h-3.5 w-3.5" />
                <span>Sign in</span>
              </Link>
            </div>
          )}

          {(drafts.length > 0 || preparing > 0) && (
            <div className="mb-2 flex gap-2 overflow-x-auto px-1 pb-1" aria-label="Pictures to send">
              {drafts.map((d) => (
                <div key={d.key} className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl border border-line bg-white">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={d.previewUrl} alt={d.name} className="h-full w-full object-cover" />
                  <button
                    type="button"
                    onClick={() => removeDraft(d.key)}
                    className="absolute right-0.5 top-0.5 rounded-full bg-ink/75 p-0.5 text-white hover:bg-ink cursor-pointer"
                    title="Remove picture"
                    aria-label={`Remove ${d.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              {Array.from({ length: preparing }).map((_, i) => (
                <div key={`preparing_${i}`} className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-line bg-line-soft" role="status" aria-label="Preparing attachment">
                  <Loader2 className="h-4 w-4 animate-spin text-ink-2" />
                </div>
              ))}
            </div>
          )}

          {fileDrafts.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2 px-1" aria-label="Files to send">
              {fileDrafts.map((d) => (
                <div key={d.key} className="inline-flex max-w-full items-center gap-1.5 rounded-xl border border-line bg-white py-1.5 pl-2.5 pr-1.5 text-xs text-ink">
                  <FileText className="h-3.5 w-3.5 shrink-0 text-ink-2" aria-hidden="true" />
                  <span className="truncate font-medium">{d.name}</span>
                  <span className="shrink-0 text-ink-2">{d.note ?? formatChars(d.chars)}</span>
                  <button
                    type="button"
                    onClick={() => removeFileDraft(d.key)}
                    className="rounded-full p-0.5 text-ink-2 hover:bg-line-soft hover:text-ink cursor-pointer"
                    title="Remove file"
                    aria-label={`Remove ${d.name}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {(voiceState === 'recording' || voiceState === 'transcribing') && (
            <div role="status" className="mb-2 flex items-center justify-between gap-2 rounded-xl border border-line bg-line-soft px-3 py-2 text-xs text-ink-2">
              {voiceState === 'recording' ? (
                <>
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-danger" aria-hidden="true" />
                    <span>
                      Listening… {formatClock(voiceSeconds)} / {formatClock(VOICE_MAX_SECONDS)}
                    </span>
                  </span>
                  <button type="button" onClick={cancelVoice} className="shrink-0 font-semibold text-ink hover:underline cursor-pointer">
                    Cancel
                  </button>
                </>
              ) : (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  Turning speech into text…
                </span>
              )}
            </div>
          )}

          <form
            onSubmit={handleSendMessage}
            className="flex items-end gap-2 rounded-3xl border border-line/90 bg-white shadow-xl shadow-ink/8 p-1.5 sm:p-2 pl-3 sm:pl-4 transition-all focus-within:border-steel focus-within:ring-2 focus-within:ring-steel/20"
          >
            <div className="flex h-10 items-center gap-2 shrink-0">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,text/*,application/pdf,.pdf,.docx,.txt,.md,.markdown,.csv,.tsv,.json,.jsonl,.yaml,.yml,.toml,.xml,.html,.css,.js,.jsx,.ts,.tsx,.py,.java,.c,.h,.cpp,.cs,.go,.rs,.rb,.php,.swift,.kt,.sql,.sh,.log,.ini,.cfg"
                multiple
                className="hidden"
                onChange={handleFilePick}
                tabIndex={-1}
                aria-hidden="true"
              />
              <button
                type="button"
                id="chat-attach-btn"
                onClick={() => fileInputRef.current?.click()}
                disabled={!canAttach}
                className="rounded-full p-2 text-ink-2 hover:text-ink hover:bg-line-soft transition-colors cursor-pointer shrink-0 disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-ink-2 disabled:cursor-not-allowed"
                title={attachTitle}
                aria-label={attachTitle}
              >
                <Paperclip className="h-4 w-4" />
              </button>
              <button
                type="button"
                id="chat-settings-btn"
                onClick={() => setShowSettings(true)}
                className={`rounded-full p-2 transition-colors cursor-pointer shrink-0 ${
                  showSettings ? 'bg-steel-soft text-steel-ink' : 'text-ink-2 hover:text-ink hover:bg-line-soft'
                }`}
                title="Settings"
                aria-label="Settings"
              >
                <SlidersHorizontal className="h-4 w-4" />
              </button>

              {/* Active Model Hint Pill (Desktop only) */}
              <div className="hidden md:flex items-center gap-1.5 rounded-full bg-line-soft px-2.5 py-1 text-[10px] font-mono text-ink-2 border border-line">
                <span className="h-1.5 w-1.5 rounded-full bg-steel" />
                <span className="font-semibold text-ink">{currentModelName}</span>
                <span aria-hidden="true">·</span>
                <span className="capitalize">{thinkingLevel} thinking</span>
              </div>
            </div>

            {/* 16px on phones: iOS Safari zooms the whole page on focus for
                anything smaller. Multi-line and auto-growing, so pasted
                code and long prompts are usable (it was a one-line field). */}
            <textarea
              ref={textareaRef}
              id="chat-input-field"
              rows={1}
              value={inputPrompt}
              maxLength={CHAT_MESSAGE_MAX_CHARS}
              onChange={(e) => setInputPrompt(e.target.value)}
              onKeyDown={handleInputKeyDown}
              onPaste={handlePaste}
              placeholder={(drafts.length > 0 || fileDrafts.length > 0) && canType ? 'Add a message about your attachments (optional)' : placeholder}
              aria-label="Message"
              disabled={!canType}
              className="flex-1 min-w-0 resize-none bg-transparent border-0 px-2 py-2 text-base sm:text-sm leading-6 text-ink placeholder:text-ink-2/70 focus:outline-none disabled:cursor-not-allowed"
            />

            {voiceSupported && (
              <button
                type="button"
                id="chat-mic-btn"
                onClick={() => (voiceState === 'recording' ? void finishVoice() : void startVoice())}
                disabled={!canType || voiceState === 'starting' || voiceState === 'transcribing'}
                className={`h-10 w-10 rounded-full flex items-center justify-center transition-colors shrink-0 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${
                  voiceState === 'recording' ? 'bg-danger text-white animate-pulse' : 'text-ink-2 hover:text-ink hover:bg-line-soft'
                }`}
                title={voiceState === 'recording' ? 'Stop and turn into text' : 'Dictate a message'}
                aria-label={voiceState === 'recording' ? 'Stop recording' : 'Dictate a message'}
                aria-pressed={voiceState === 'recording'}
              >
                {voiceState === 'starting' || voiceState === 'transcribing' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : voiceState === 'recording' ? (
                  <Square className="h-4 w-4 fill-current" />
                ) : (
                  <Mic className="h-4 w-4" />
                )}
              </button>
            )}

            <button
              type="submit"
              id="chat-send-btn"
              disabled={!canType || (!inputPrompt.trim() && drafts.length === 0 && fileDrafts.length === 0) || preparing > 0 || isGenerating || voiceState !== 'idle'}
              className="h-10 w-10 rounded-full bg-steel hover:bg-steel-hover text-white flex items-center justify-center shadow-md shadow-steel/30 transition-all disabled:opacity-40 disabled:hover:bg-steel disabled:cursor-not-allowed cursor-pointer shrink-0"
              title="Send message"
              aria-label="Send message"
            >
              <ArrowUp className="h-5 w-5 stroke-[2.5]" />
            </button>
          </form>

          {nearLimit && (
            <p className="mt-1 px-3 text-right text-[10px] font-mono text-ink-2">
              {inputPrompt.length.toLocaleString()} / {CHAT_MESSAGE_MAX_CHARS.toLocaleString()}
            </p>
          )}
        </div>
      </div>

      {/* Settings modal — a true full-screen overlay (bottom sheet on mobile,
          centered card on larger screens). z-[150] puts it above the navbar
          (z-100); it was z-60, so the navbar painted over it. Two settings: the
          model (Kael Beta or Kael Pro Beta), which a conversation keeps once it
          has started, and the thinking level (Kael's reasoning_effort), which
          depends on the model and is sent with each message. */}
      {showSettings && (
        <div
          className="fixed inset-0 z-[150] flex items-end sm:items-center justify-center bg-ink/50 backdrop-blur-xs"
          onClick={() => setShowSettings(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-dialog-title"
            onClick={(e) => e.stopPropagation()}
            className="w-full sm:w-[380px] rounded-t-2xl sm:rounded-2xl border border-line bg-white p-4 sm:p-5 shadow-2xl space-y-4 max-h-[85vh] overflow-y-auto"
          >
            <div className="flex items-center justify-between">
              <span id="settings-dialog-title" className="text-sm font-bold text-ink">
                Settings
              </span>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="rounded-2xl p-1.5 text-ink-2 hover:bg-line-soft hover:text-ink cursor-pointer"
                title="Close"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div role="radiogroup" aria-labelledby="model-label" className="space-y-2">
              <span id="model-label" className="block text-xs font-semibold text-ink">
                Model
              </span>
              <div className="space-y-1.5">
                {MODELS.map((m) => {
                  const selected = activeModel === m.id;
                  return (
                    <button
                      key={m.id}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      disabled={modelLocked}
                      onClick={() => setSelectedModel(m.id)}
                      className={`w-full rounded-xl border px-3 py-2 text-left transition-colors ${
                        selected ? 'border-steel bg-steel-soft' : 'border-line bg-white hover:border-ink-3'
                      } ${modelLocked ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}`}
                    >
                      <span className="block text-xs font-semibold text-ink">{m.name}</span>
                      <span className="block text-xs leading-snug text-ink-2">{m.summary}</span>
                    </button>
                  );
                })}
              </div>
              {modelLocked && <p className="text-xs text-ink-2">Fixed for this chat.</p>}
            </div>

            <div role="radiogroup" aria-labelledby="thinking-level-label" className="space-y-2">
              <span id="thinking-level-label" className="block text-xs font-semibold text-ink">
                Thinking
              </span>
              <div
                className="grid gap-1 rounded-xl bg-line-soft p-1"
                title="Higher levels think longer and take more time"
                style={{ gridTemplateColumns: `repeat(${activeModelInfo.levels.length}, minmax(0, 1fr))` }}
              >
                {activeModelInfo.levels.map((level: ThinkingLevel) => {
                  const selected = thinkingLevel === level;
                  return (
                    <button
                      key={level}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() => setThinkingLevel(level)}
                      className={`rounded-lg py-1.5 text-xs font-semibold capitalize transition-colors cursor-pointer ${
                        selected ? 'bg-white text-ink shadow-xs' : 'text-ink-2 hover:text-ink'
                      }`}
                    >
                      {level}
                    </button>
                  );
                })}
              </div>
            </div>

            <button
              type="button"
              autoFocus
              onClick={() => setShowSettings(false)}
              className="w-full rounded-xl bg-ink py-2 text-xs font-bold text-white hover:opacity-90 transition-opacity cursor-pointer"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
