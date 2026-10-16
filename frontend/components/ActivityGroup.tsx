"use client";

import type { ReactNode } from "react";
import { ChevronIcon, Spinner } from "./icons";

/**
 * One collapsed line standing in for a run of the agent's work — "Read a file, ran 10 commands" —
 * with the tool calls and mid-turn narration inside, closed by default. While the agent is still
 * working it shows a spinner and the step it is on, so the person can see it is alive without the
 * transcript filling up.
 *
 * A native <details>: it needs no state, works with the keyboard and screen readers, and React
 * never touches its `open` attribute, so a group the person opened stays open as the agent adds to
 * it (the parent keys each group by its first event, which never changes).
 */
export default function ActivityGroup({
  summary,
  latest,
  live,
  failed,
  children,
}: {
  summary: string;
  /** The newest tool call, one line. Shown only while `live`. */
  latest: string | null;
  live: boolean;
  failed: number;
  children: ReactNode;
}) {
  return (
    <details className="group text-sm">
      <summary className="list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none min-h-[40px] flex flex-col justify-center text-muted">
        <span className="flex items-center gap-1.5 min-w-0">
          {live && <Spinner className="w-3.5 h-3.5 flex-none" />}
          <span className="truncate">
            {summary}
            {failed > 0 && <span className="text-accent"> · {failed} failed</span>}
          </span>
          <ChevronIcon className="w-4 h-4 flex-none transition-transform group-open:rotate-90" />
        </span>
        {live && latest && <span className="mono text-xs truncate mt-0.5">{latest}</span>}
      </summary>
      <div className="mt-1 ml-1.5 pl-3 border-l border-line space-y-2 pb-1">{children}</div>
    </details>
  );
}
