import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api.js';
import ErrorBanner from '../components/ErrorBanner.jsx';

const EMPTY_PROVIDER_FORM = { id: '', label: '', baseUrl: '', model: '', apiKey: '', reasoningEfforts: '' };
const EMPTY_SECRET_FORM = { key: '', label: '', value: '' };

export default function Settings() {
  const [providers, setProviders] = useState(null);
  const [secrets, setSecrets] = useState(null);
  const [error, setError] = useState(null);

  const [providerForm, setProviderForm] = useState(EMPTY_PROVIDER_FORM);
  const [editingProviderId, setEditingProviderId] = useState(null);
  const [savingProvider, setSavingProvider] = useState(false);

  const [secretForm, setSecretForm] = useState(EMPTY_SECRET_FORM);
  const [editingSecretKey, setEditingSecretKey] = useState(null);
  const [savingSecret, setSavingSecret] = useState(false);

  useEffect(() => {
    refreshProviders();
    refreshSecrets();
  }, []);

  function refreshProviders() {
    return api
      .listProviderSettings()
      .then((data) => setProviders(data.providers))
      .catch((err) => setError(err.message));
  }

  function refreshSecrets() {
    return api
      .listSecrets()
      .then((data) => setSecrets(data.secrets))
      .catch((err) => setError(err.message));
  }

  function startEditProvider(p) {
    setEditingProviderId(p.id);
    setProviderForm({
      id: p.id,
      label: p.label || '',
      baseUrl: p.baseUrl || '',
      model: p.model || '',
      apiKey: '',
      reasoningEfforts: (p.reasoningEfforts || []).join(','),
    });
  }

  function cancelEditProvider() {
    setEditingProviderId(null);
    setProviderForm(EMPTY_PROVIDER_FORM);
  }

  async function handleSaveProvider(e) {
    e.preventDefault();
    if (!providerForm.id.trim()) return;
    setSavingProvider(true);
    setError(null);
    try {
      await api.saveProviderSetting(providerForm.id.trim(), {
        label: providerForm.label.trim(),
        baseUrl: providerForm.baseUrl.trim(),
        model: providerForm.model.trim(),
        apiKey: providerForm.apiKey.trim(), // blank on an edit keeps the existing key (backend handles this)
        reasoningEfforts: providerForm.reasoningEfforts.trim(),
      });
      cancelEditProvider();
      await refreshProviders();
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingProvider(false);
    }
  }

  async function handleDeleteProvider(id) {
    if (!window.confirm(`Remove provider '${id}'? Any session still set to it will need to switch providers.`)) return;
    setError(null);
    try {
      await api.deleteProviderSetting(id);
      if (editingProviderId === id) cancelEditProvider();
      await refreshProviders();
    } catch (err) {
      setError(err.message);
    }
  }

  function startEditSecret(s) {
    setEditingSecretKey(s.key);
    setSecretForm({ key: s.key, label: s.label || '', value: '' });
  }

  function cancelEditSecret() {
    setEditingSecretKey(null);
    setSecretForm(EMPTY_SECRET_FORM);
  }

  async function handleSaveSecret(e) {
    e.preventDefault();
    if (!secretForm.key.trim()) return;
    setSavingSecret(true);
    setError(null);
    try {
      await api.saveSecret(secretForm.key.trim(), secretForm.value.trim(), secretForm.label.trim());
      cancelEditSecret();
      await refreshSecrets();
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingSecret(false);
    }
  }

  async function handleDeleteSecret(key) {
    if (!window.confirm(`Remove the saved key '${key}'? Anything that uses it will stop working until you add it again.`)) return;
    setError(null);
    try {
      await api.deleteSecret(key);
      if (editingSecretKey === key) cancelEditSecret();
      await refreshSecrets();
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <Link to="/" className="back-link">
          ← Projects
        </Link>
        <div className="page-header-row">
          <h1>Settings</h1>
        </div>
      </header>

      <ErrorBanner message={error} onDismiss={() => setError(null)} />

      <section>
        <h2>Model providers</h2>
        <p className="muted small">
          Any endpoint that speaks the OpenAI Responses API shape — OpenAI itself, DeepSeek, Azure OpenAI, a
          self-hosted gateway. The first one you add becomes the default for new sessions; add a second and a
          switcher appears in the composer.
        </p>

        {providers === null ? (
          <p className="muted">Loading…</p>
        ) : providers.length === 0 ? (
          <p className="muted">No providers configured yet — add one below.</p>
        ) : (
          <div className="stack">
            {providers.map((p) => (
              <div className="card settings-item" key={p.id}>
                <div className="settings-item-main">
                  <strong>{p.label}</strong> <span className="badge small">{p.id}</span>
                  <p className="muted small">
                    {p.model} · {p.baseUrl}
                  </p>
                  <p className="muted small">
                    Key: {p.apiKeyPreview || 'not set'}
                    {' · '}
                    {p.reasoningEfforts?.length ? `effort: ${p.reasoningEfforts.join(', ')}` : 'no reasoning-effort param'}
                  </p>
                </div>
                <div className="settings-item-actions">
                  <button type="button" className="ghost" onClick={() => startEditProvider(p)}>
                    Edit
                  </button>
                  <button type="button" className="ghost" onClick={() => handleDeleteProvider(p.id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleSaveProvider} className="stack card">
          <h2>{editingProviderId ? `Edit provider · ${editingProviderId}` : 'Add provider'}</h2>
          <label>
            Provider id
            <input
              value={providerForm.id}
              onChange={(e) => setProviderForm({ ...providerForm, id: e.target.value })}
              disabled={!!editingProviderId}
              placeholder="e.g. openai, deepseek, my-gateway"
              required
            />
          </label>
          <label>
            Label
            <input
              value={providerForm.label}
              onChange={(e) => setProviderForm({ ...providerForm, label: e.target.value })}
              placeholder="Shown in the provider switch"
            />
          </label>
          <label>
            Base URL
            <input
              value={providerForm.baseUrl}
              onChange={(e) => setProviderForm({ ...providerForm, baseUrl: e.target.value })}
              placeholder="https://api.openai.com/v1"
              required={!editingProviderId}
            />
          </label>
          <label>
            Model
            <input
              value={providerForm.model}
              onChange={(e) => setProviderForm({ ...providerForm, model: e.target.value })}
              placeholder="e.g. gpt-5"
            />
          </label>
          <label>
            API key{editingProviderId && <span className="muted small"> — leave blank to keep the saved key</span>}
            <input
              type="password"
              value={providerForm.apiKey}
              onChange={(e) => setProviderForm({ ...providerForm, apiKey: e.target.value })}
              placeholder={editingProviderId ? 'unchanged' : 'required'}
              autoComplete="off"
              required={!editingProviderId}
            />
          </label>
          <label>
            Reasoning efforts (comma-separated, optional)
            <input
              value={providerForm.reasoningEfforts}
              onChange={(e) => setProviderForm({ ...providerForm, reasoningEfforts: e.target.value })}
              placeholder="low,high,max — leave blank if the model takes no reasoning param"
            />
          </label>
          <div className="form-actions">
            <button type="submit" disabled={savingProvider}>
              {savingProvider ? 'Saving…' : editingProviderId ? 'Save changes' : '+ Add provider'}
            </button>
            {editingProviderId && (
              <button type="button" className="ghost" onClick={cancelEditProvider}>
                Cancel
              </button>
            )}
          </div>
        </form>
      </section>

      <section>
        <h2>Other API keys</h2>
        <p className="muted small">
          The harness looks for these by key name: <code>github_token</code> (PAT with the <code>repo</code> scope),{' '}
          <code>vercel_token</code>, <code>vercel_team_id</code> (optional, team accounts only), and{' '}
          <code>tavily_api_key</code>.
        </p>

        {secrets === null ? (
          <p className="muted">Loading…</p>
        ) : secrets.length === 0 ? (
          <p className="muted">No keys saved yet — add one below.</p>
        ) : (
          <div className="stack">
            {secrets.map((s) => (
              <div className="card settings-item" key={s.key}>
                <div className="settings-item-main">
                  <strong>{s.label}</strong> <span className="badge small">{s.key}</span>
                  <p className="muted small">{s.hasValue ? 'Value saved' : 'Not set'}</p>
                </div>
                <div className="settings-item-actions">
                  <button type="button" className="ghost" onClick={() => startEditSecret(s)}>
                    Edit
                  </button>
                  <button type="button" className="ghost" onClick={() => handleDeleteSecret(s.key)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleSaveSecret} className="stack card">
          <h2>{editingSecretKey ? `Edit key · ${editingSecretKey}` : 'Add API key'}</h2>
          <label>
            Key name
            <input
              value={secretForm.key}
              onChange={(e) => setSecretForm({ ...secretForm, key: e.target.value })}
              disabled={!!editingSecretKey}
              placeholder="e.g. github_token, vercel_token, tavily_api_key"
              required
            />
          </label>
          <label>
            Label
            <input
              value={secretForm.label}
              onChange={(e) => setSecretForm({ ...secretForm, label: e.target.value })}
              placeholder="What this key is for"
            />
          </label>
          <label>
            Value{editingSecretKey && <span className="muted small"> — leave blank to keep the saved value</span>}
            <input
              type="password"
              value={secretForm.value}
              onChange={(e) => setSecretForm({ ...secretForm, value: e.target.value })}
              placeholder={editingSecretKey ? 'unchanged' : 'required'}
              autoComplete="off"
              required={!editingSecretKey}
            />
          </label>
          <div className="form-actions">
            <button type="submit" disabled={savingSecret}>
              {savingSecret ? 'Saving…' : editingSecretKey ? 'Save changes' : '+ Add key'}
            </button>
            {editingSecretKey && (
              <button type="button" className="ghost" onClick={cancelEditSecret}>
                Cancel
              </button>
            )}
          </div>
        </form>
      </section>
    </main>
  );
}
