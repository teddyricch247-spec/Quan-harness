"use client";

import { useCallback, useState } from "react";

/**
 * Phase Convert (C7): which sheet is open. A workspace has one ⋯ menu and a handful of sheets
 * behind it; only one is ever visible, so this is a single nullable name rather than a boolean per
 * sheet. `T` is the union of the page's sheet names.
 */
export function useSheet<T extends string>(): { current: T | null; open: (name: T) => void; close: () => void; is: (name: T) => boolean } {
  const [current, setCurrent] = useState<T | null>(null);
  const open = useCallback((name: T) => setCurrent(name), []);
  const close = useCallback(() => setCurrent(null), []);
  const is = useCallback((name: T) => current === name, [current]);
  return { current, open, close, is };
}
