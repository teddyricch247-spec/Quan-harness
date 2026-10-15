"use client";

import { useEffect, useState } from "react";
import { clearReturnTo, peekReturnTo } from "@/lib/returnTo";
import TopBar from "./TopBar";

/**
 * Phase Convert (C6/C7): the frame for Settings and the pages behind it — a TopBar with a back
 * arrow (to Settings by default) and a scrolling content column. Page bodies keep their own
 * fields and behavior unchanged; only the header changed.
 *
 * If Code home sent the person here to connect something (a model key, GitHub), the back arrow
 * goes back to where they came from instead, with their draft intact (C4) — see lib/returnTo.ts.
 */
export default function PageFrame({
  title,
  back = "/settings",
  right,
  narrow = false,
  children,
}: {
  title: React.ReactNode;
  back?: string;
  right?: React.ReactNode;
  narrow?: boolean; // the old pages were all max-w-5xl; keep that unless a page asks otherwise
  children: React.ReactNode;
}) {
  const [returnTo, setReturnToState] = useState<string | null>(null);
  useEffect(() => setReturnToState(peekReturnTo()), []);

  return (
    <>
      <TopBar title={title} back={returnTo ?? back} onBack={returnTo ? clearReturnTo : undefined} right={right} />
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className={`mx-auto w-full ${narrow ? "max-w-3xl" : "max-w-5xl"} px-4 pt-2 pb-10`}>{children}</div>
      </div>
    </>
  );
}
