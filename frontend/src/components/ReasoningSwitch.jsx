const LEVELS = [
  { value: 'low', label: 'Low' },
  { value: 'high', label: 'High' },
  { value: 'max', label: 'Max' },
];

// Only three positions on purpose — see README "About the thinking switch" for why
// there's no separate "Medium". Whatever is selected here is sent as
// reasoning.effort on every DeepSeek call for the turn: the main agent's rounds AND
// the verifier that runs after finish_task.
export default function ReasoningSwitch({ value, onChange, disabled }) {
  return (
    <div className="reasoning-switch" role="group" aria-label="Thinking effort">
      {LEVELS.map((level) => (
        <button
          key={level.value}
          type="button"
          className={value === level.value ? 'active' : ''}
          disabled={disabled}
          onClick={() => onChange(level.value)}
        >
          {level.label}
        </button>
      ))}
    </div>
  );
}
