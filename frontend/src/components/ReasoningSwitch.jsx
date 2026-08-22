function label(level) {
  return level.charAt(0).toUpperCase() + level.slice(1);
}

// Positions come from whichever provider the session is currently using (see
// ProviderSwitch.jsx + SessionView.jsx) rather than being hardcoded here — DeepSeek
// exposes low/high/max (see README "About the thinking switch" for why there's no
// separate "medium"), but a custom provider might expose a different set, or none at
// all, in which case this renders nothing.
export default function ReasoningSwitch({ value, onChange, disabled, efforts }) {
  if (!efforts || efforts.length === 0) return null;

  return (
    <div className="reasoning-switch" role="group" aria-label="Thinking effort">
      {efforts.map((level) => (
        <button
          key={level}
          type="button"
          className={value === level ? 'active' : ''}
          disabled={disabled}
          onClick={() => onChange(level)}
        >
          {label(level)}
        </button>
      ))}
    </div>
  );
}
