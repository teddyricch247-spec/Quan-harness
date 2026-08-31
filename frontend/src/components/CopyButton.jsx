import { useEffect, useRef, useState } from 'react';

// Falls back to a hidden textarea + execCommand when the async Clipboard API isn't
// available (older browsers, or any non-secure-context http:// during local dev).
function copyText(text) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const el = document.createElement('textarea');
    el.value = text;
    el.style.position = 'fixed';
    el.style.opacity = '0';
    document.body.appendChild(el);
    el.select();
    try {
      document.execCommand('copy');
      resolve();
    } catch (err) {
      reject(err);
    } finally {
      document.body.removeChild(el);
    }
  });
}

export default function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef(null);

  useEffect(() => () => clearTimeout(timeoutRef.current), []);

  async function handleClick() {
    try {
      await copyText(text);
      setCopied(true);
      clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard genuinely unavailable — nothing more we can do here
    }
  }

  return (
    <button
      type="button"
      className="copy-btn"
      onClick={handleClick}
      aria-label={copied ? 'Copied' : 'Copy message'}
    >
      {copied ? (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <polyline points="20 6 9 17 4 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <rect x="9" y="9" width="12" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}
