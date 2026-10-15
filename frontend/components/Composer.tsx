"use client";

import { useEffect, useRef } from "react";
import { PlusIcon, SendIcon, Spinner } from "./icons";

/**
 * Phase Convert (C7): the one composer, shared by Code home and the workspace. The props choose the
 * controls — Code home passes the + (project setup), a source chip and the model chip; the
 * workspace passes its own + (this project) and the model chip.
 *
 * - The send button is dark when there is something to send, grey otherwise.
 * - Enter sends on a device with a fine pointer; on a phone Enter is a newline and the send button
 *   sends. Ctrl/Cmd+Enter sends everywhere. Shift+Enter is always a newline.
 * - `busyLabel` (e.g. "Importing you/repo…") disables input and shows what is happening.
 */
export default function Composer({
  value,
  onChange,
  onSend,
  placeholder,
  disabled = false,
  busyLabel = null,
  allowEmptySend = false,
  blockSend = false,
  onPlus,
  plusLabel = "Add",
  modelLabel,
  onModel,
  chips,
  autoFocus = false,
  sendLabel = "Send",
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  placeholder?: string;
  disabled?: boolean;
  busyLabel?: string | null;
  allowEmptySend?: boolean; // an import can be sent with nothing typed; a message with a picture can too
  blockSend?: boolean; // e.g. a picture is still being prepared
  onPlus?: () => void;
  plusLabel?: string;
  modelLabel?: string | null;
  onModel?: () => void;
  chips?: React.ReactNode;
  autoFocus?: boolean;
  sendLabel?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const canSend = !disabled && !busyLabel && !blockSend && (allowEmptySend || value.trim().length > 0);

  // Grow with the text up to about eight lines, then scroll.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // Focus once the box is actually enabled — on Code home it starts disabled until the saved draft
  // has loaded, and focusing a disabled textarea does nothing.
  useEffect(() => {
    if (autoFocus && !disabled && !busyLabel) ref.current?.focus();
  }, [autoFocus, disabled, busyLabel]);

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    const coarse = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches;
    if (e.metaKey || e.ctrlKey || !coarse) {
      e.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <div className="mx-3 desk:mx-4 bg-white border border-line rounded-[18px] px-3.5 pt-3 pb-2.5 flex-none mb-[max(0.75rem,env(safe-area-inset-bottom))]">
      {(chips || busyLabel) && (
        <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
          {busyLabel && (
            <span className="inline-flex items-center gap-1.5 text-[13px] border border-line rounded-full px-2.5 py-0.5 bg-paper" role="status">
              <Spinner className="w-3.5 h-3.5" /> {busyLabel}
            </span>
          )}
          {chips}
        </div>
      )}
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled || !!busyLabel}
        rows={2}
        aria-label={placeholder ?? "Message"}
        className="w-full resize-none border-0 outline-none bg-transparent min-h-[48px] disabled:opacity-60"
      />
      <div className="flex items-center gap-2">
        {onPlus && (
          <button
            type="button"
            onClick={onPlus}
            aria-label={plusLabel}
            disabled={!!busyLabel}
            className="w-9 h-9 grid place-items-center rounded-full bg-soft text-[#555] disabled:opacity-50"
          >
            <PlusIcon />
          </button>
        )}
        {onModel && (
          <button type="button" onClick={onModel} className="text-sm text-[#555] px-1.5 py-1 min-h-[36px] max-w-[45%] truncate" aria-label="Change model">
            {modelLabel ?? "Model"}
          </button>
        )}
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          aria-label={sendLabel}
          className={`ml-auto w-9 h-9 grid place-items-center rounded-full text-white ${canSend ? "bg-ink" : "bg-[#aaa]"}`}
        >
          <SendIcon />
        </button>
      </div>
    </div>
  );
}
