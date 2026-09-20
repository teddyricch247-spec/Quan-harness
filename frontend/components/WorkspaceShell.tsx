"use client";

/**
 * §11.2's Workspace screen layout — desktop is chat-left/preview-right,
 * two panes side by side; below a fixed breakpoint, §11.1's implementation
 * order calls for this explicitly: "the mobile single-column collapse
 * behavior (§11) from the start." A tab bar switches between the two panes,
 * never both on screen at once on a narrow viewport, and switching preserves
 * each pane's own scroll position because neither pane unmounts — they're
 * just toggled between `block` and `hidden`, not conditionally rendered.
 *
 * Phase 1 has nothing real to put in either pane yet — the turn loop (chat)
 * is Phase 3, Live Preview is Phase 5 (§23) — so `/projects/[id]/page.tsx`
 * passes honest placeholder content into `left`/`right` for now. Standing
 * the shell up now means neither of those later phases has to revisit this
 * layout, only fill in what each pane actually renders.
 */
import { useState } from "react";

export default function WorkspaceShell({
  leftLabel,
  rightLabel,
  left,
  right,
}: {
  leftLabel: string;
  rightLabel: string;
  left: React.ReactNode;
  right: React.ReactNode;
}) {
  const [activePane, setActivePane] = useState<"left" | "right">("left");

  return (
    <div>
      {/* Tab bar — lg:hidden mirrors the breakpoint the two-column grid below
          switches on, so exactly one of these ever shows at a time. */}
      <div className="lg:hidden flex gap-1 mb-3 border border-line rounded-md p-1 bg-white">
        <button
          onClick={() => setActivePane("left")}
          className={`flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
            activePane === "left" ? "bg-paper text-ink" : "text-muted"
          }`}
        >
          {leftLabel}
        </button>
        <button
          onClick={() => setActivePane("right")}
          className={`flex-1 rounded px-3 py-1.5 text-sm font-medium transition-colors ${
            activePane === "right" ? "bg-paper text-ink" : "text-muted"
          }`}
        >
          {rightLabel}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className={activePane === "left" ? "block" : "hidden lg:block"}>{left}</div>
        <div className={activePane === "right" ? "block" : "hidden lg:block"}>{right}</div>
      </div>
    </div>
  );
}
