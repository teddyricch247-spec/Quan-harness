"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Phase Convert (C4, "Do drafts survive tab switches and reloads?"): yes. One draft per surface —
 * Chat, Code home, and each project — stored client-side, keyed by surface and project id.
 *
 * Keys the app uses: "code-home", "chat", `project:${id}`. localStorage failing (private mode,
 * quota) degrades to an ordinary in-memory draft; it never throws into a render.
 */
const PREFIX = "qh:draft:";

function read(key: string): string {
  try {
    return window.localStorage.getItem(PREFIX + key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string): void {
  try {
    if (value) window.localStorage.setItem(PREFIX + key, value);
    else window.localStorage.removeItem(PREFIX + key);
  } catch {
    // ignore — see above
  }
}

export function useDraft(key: string): { draft: string; setDraft: (v: string) => void; clearDraft: () => void; ready: boolean } {
  const [draft, setDraftState] = useState("");
  const [ready, setReady] = useState(false);
  const keyRef = useRef(key);
  keyRef.current = key;

  // Loaded in an effect, not in the initial state, so server and first client render agree.
  useEffect(() => {
    setDraftState(read(key));
    setReady(true);
  }, [key]);

  const setDraft = useCallback((value: string) => {
    setDraftState(value);
    write(keyRef.current, value);
  }, []);

  const clearDraft = useCallback(() => {
    setDraftState("");
    write(keyRef.current, "");
  }, []);

  return { draft, setDraft, clearDraft, ready };
}

/** Write a draft for a key this component isn't currently using — e.g. Code home leaving a
 * rejected import prompt behind as the new project's workspace draft (C4, "If the pull fails…"). */
export function saveDraft(key: string, value: string): void {
  write(key, value);
}
