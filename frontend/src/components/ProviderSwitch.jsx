// Renders nothing when there's only one provider configured (the common case: just
// DeepSeek) — no point showing a switch with a single, unchangeable option. Appears
// automatically once a custom provider is set up on the backend (see
// backend/.env.example's CUSTOM_* vars and GET /api/meta).
export default function ProviderSwitch({ value, onChange, disabled, providers }) {
  if (!providers || providers.length < 2) return null;

  return (
    <div className="provider-switch" role="group" aria-label="Model provider">
      {providers.map((p) => (
        <button
          key={p.id}
          type="button"
          className={value === p.id ? 'active' : ''}
          disabled={disabled}
          onClick={() => onChange(p.id)}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}
