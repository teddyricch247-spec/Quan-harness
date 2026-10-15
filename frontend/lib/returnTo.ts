"use client";

/**
 * Phase Convert (C4): "the send button routes to LLM Providers … After saving, the user returns to
 * Code home with their draft intact", and likewise "Connect GitHub first →" goes to the GitHub
 * page "and returns with the draft intact". The draft itself lives in localStorage (useDraft); this
 * is only the breadcrumb for where the back arrow should go. sessionStorage, so it survives the
 * GitHub OAuth round-trip (same tab) but not a new session.
 */
const KEY = "qh:return-to";

export function setReturnTo(path: string): void {
  try {
    window.sessionStorage.setItem(KEY, path);
  } catch {
    // ignore
  }
}

export function peekReturnTo(): string | null {
  try {
    const value = window.sessionStorage.getItem(KEY);
    // Same-origin paths only — never an open redirect.
    return value && value.startsWith("/") && !value.startsWith("//") ? value : null;
  } catch {
    return null;
  }
}

export function clearReturnTo(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // ignore
  }
}
