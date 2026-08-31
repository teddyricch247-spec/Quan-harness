import CopyButton from './CopyButton.jsx';

/**
 * One chat bubble plus its (optional) copy action, aligned left or right by `role`.
 * `copyText` is the plain text that gets copied — pass it explicitly rather than
 * deriving it from `children`, since a bubble's children are often richer than its
 * copyable content (e.g. the build-turn summary bubble also shows verifier/critique
 * notes underneath the summary, but only the summary itself is worth copying).
 * Omit `copyText` for bubbles with nothing worth copying (e.g. the handoff bubble).
 */
export default function MessageBubble({ role, children, copyText, className = '' }) {
  return (
    <div className={`bubble-row ${role}`}>
      <div className={`bubble ${role} ${className}`.trim()}>{children}</div>
      {copyText && (
        <div className="bubble-actions">
          <CopyButton text={copyText} />
        </div>
      )}
    </div>
  );
}
