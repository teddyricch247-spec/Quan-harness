"use client";

import { useEffect, useRef } from "react";
import { CloseIcon } from "./icons";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Phase Convert (C7): the one overlay pattern. A bottom sheet below 900 px, a centered dialog from
 * 900 px up. Behavior the spec names: focus trap, Escape, scrim click. Also: focus returns to
 * whatever opened it, and the page behind does not scroll while it is open.
 *
 * Content is mounted only while `open`, so a sheet's own data fetching (checkpoints, secrets…)
 * happens when it is opened and stops when it is closed.
 */
export default function Sheet({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    // Focus the panel itself (not the first control) so a screen reader announces the title first
    // and a phone doesn't pop the keyboard for a sheet that happens to start with an input.
    panel?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end desk:items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={`relative w-full ${wide ? "desk:max-w-[640px]" : "desk:max-w-[520px]"} max-h-[88dvh] flex flex-col bg-white rounded-t-2xl desk:rounded-2xl outline-none shadow-xl`}
      >
        <div className="flex items-center gap-2 pl-4 pr-2 min-h-[52px] border-b border-line flex-none">
          <h2 className="flex-1 font-semibold truncate">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="w-9 h-9 grid place-items-center rounded-lg hover:bg-paper">
            <CloseIcon />
          </button>
        </div>
        <div className="overflow-y-auto min-h-0 flex-1 pb-safe-bottom">{children}</div>
      </div>
    </div>
  );
}
