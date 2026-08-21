import { useState } from 'react';

export default function ThinkingBlock({ text, live }) {
  const [open, setOpen] = useState(true);
  if (!text) return null;

  return (
    <div className="thinking-block">
      <button type="button" className="ghost thinking-toggle" onClick={() => setOpen((o) => !o)}>
        {live ? 'Thinking…' : 'Thinking'} {open ? '▾' : '▸'}
      </button>
      {open && <p className="thinking-text">{text}</p>}
    </div>
  );
}
