import { useState } from 'react';
import ReasoningSwitch from './ReasoningSwitch.jsx';

export default function Composer({ effort, onEffortChange, onSend, busy }) {
  const [text, setText] = useState('');

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
    setText('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="composer">
      <ReasoningSwitch value={effort} onChange={onEffortChange} disabled={busy} />
      <div className="composer-row">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={busy ? 'Working…' : 'Describe what to change…'}
          disabled={busy}
          rows={2}
        />
        <button type="submit" disabled={busy || !text.trim()}>
          {busy ? '…' : 'Send'}
        </button>
      </div>
    </form>
  );
}
