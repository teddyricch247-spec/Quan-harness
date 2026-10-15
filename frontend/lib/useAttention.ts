"use client";

import { useCallback, useEffect, useState } from "react";
import { getAttention } from "./api";
import type { AttentionOut } from "./types";

const POLL_MS = 20_000;
const ZERO: AttentionOut = { code: { waiting_approval: 0, failed: 0 }, chat: { waiting_approval: 0, failed: 0 } };

/**
 * Phase Convert (C4/C8.3): the red dot on a tab. Polls GET /attention about every 20 s while the
 * tab is visible, and again whenever the window regains focus. A failed poll keeps the last good
 * answer — a flaky network must not make a real "needs you" dot vanish.
 */
export function useAttention(enabled: boolean): { attention: AttentionOut; refresh: () => void } {
  const [attention, setAttention] = useState<AttentionOut>(ZERO);

  const refresh = useCallback(() => {
    getAttention()
      .then(setAttention)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!enabled) return;
    refresh();
    const interval = setInterval(() => {
      if (!document.hidden) refresh();
    }, POLL_MS);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", refresh);
    };
  }, [enabled, refresh]);

  return { attention, refresh };
}

export function needsYou(counts: { waiting_approval: number; failed: number }): boolean {
  return counts.waiting_approval + counts.failed > 0;
}
