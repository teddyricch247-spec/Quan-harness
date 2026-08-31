import { useEffect, useRef, useState } from 'react';

/**
 * `live` is only ever true for the one ThinkingBlock instance rendered while a turn
 * is actively streaming (see SessionView's `{live && <ThinkingBlock ... live />}`
 * block) — that instance is unmounted the moment the turn finishes, and a fresh,
 * non-live instance takes its place once the turn reloads from the database. So this
 * component never needs to handle a live→non-live transition mid-life: each instance
 * is either live for its whole existence, or never live at all. That's also why a
 * finished turn's duration isn't shown here — the live instance that knew it is gone
 * by the time the persisted one mounts, and that's fine: reasoning text itself is
 * still one tap away.
 */
export default function ThinkingBlock({ text, live }) {
  const [open, setOpen] = useState(!!live);
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(null);

  useEffect(() => {
    if (!live) return undefined;
    if (startRef.current === null) startRef.current = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(id);
  }, [live]);

  if (!text) return null;

  const label = live ? `Thinking${elapsed ? ` · ${elapsed}s` : '…'}` : 'Thinking';

  return (
    <div className="thinking-block">
      <button type="button" className="ghost thinking-toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span>{label}</span>
        <span className="thinking-caret">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <p className="thinking-text">
          {text}
          {live && <span className="thinking-cursor" aria-hidden="true" />}
        </p>
      )}
    </div>
  );
}
