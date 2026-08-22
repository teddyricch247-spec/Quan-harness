import { useState } from 'react';
import ReasoningSwitch from './ReasoningSwitch.jsx';
import ProviderSwitch from './ProviderSwitch.jsx';

export default function Composer({
  effort,
  efforts,
  onEffortChange,
  provider,
  providers,
  onProviderChange,
  onSend,
  busy,
  placeholder,
}) {
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
      <div className="composer-switches">
        <ProviderSwitch value={provider} onChange={onProviderChange} disabled={busy} providers={providers} />
        <ReasoningSwitch value={effort} onChange={onEffortChange} disabled={busy} efforts={efforts} />
      </div>
      <div className="composer-row">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={busy ? 'Working…' : placeholder || 'Describe what to change…'}
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
