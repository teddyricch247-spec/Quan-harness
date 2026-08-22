import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../lib/api.js';

const MODE_KEY = 'harness.newSessionMode';

// Prompt Maker is the default the very first time this ever runs on a device — after
// that, it remembers whatever the user picked last.
function loadDefaultMode() {
  try {
    return localStorage.getItem(MODE_KEY) === 'build' ? 'build' : 'interview';
  } catch {
    return 'interview';
  }
}

export default function SessionList() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [mode, setMode] = useState(loadDefaultMode);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((err) => setError(err.message));
    refresh();
  }, [projectId]);

  function refresh() {
    api
      .listSessions(projectId)
      .then(setSessions)
      .catch((err) => setError(err.message));
  }

  function handleModeChange(next) {
    setMode(next);
    try {
      localStorage.setItem(MODE_KEY, next);
    } catch {
      // private browsing / storage disabled — the toggle still works for this tab
    }
  }

  async function handleNewSession() {
    setCreating(true);
    setError(null);
    try {
      const session = await api.createSession(projectId, 'New session', mode);
      navigate(`/project/${projectId}/session/${session.id}`);
    } catch (err) {
      setError(err.message);
      setCreating(false);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <Link to="/" className="back-link">
          ← Projects
        </Link>
        <h1>{project?.name || '…'}</h1>
      </header>

      {error && <p className="error">{error}</p>}

      {sessions === null ? (
        <p className="muted">Loading…</p>
      ) : sessions.length === 0 ? (
        <p className="muted">No sessions yet.</p>
      ) : (
        <ul className="list">
          {sessions.map((s) => (
            <li key={s.id}>
              <span>
                <Link to={`/project/${projectId}/session/${s.id}`}>{s.title}</Link>
                {s.kind === 'interview' && <span className="badge small">Prompt Maker</span>}
              </span>
              <span className="muted"> {new Date(s.updated_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="card stack">
        <h2>New session</h2>
        <div className="mode-toggle" role="group" aria-label="New session mode">
          <button type="button" className={mode === 'interview' ? 'active' : ''} onClick={() => handleModeChange('interview')}>
            Prompt Maker
          </button>
          <button type="button" className={mode === 'build' ? 'active' : ''} onClick={() => handleModeChange('build')}>
            Direct build
          </button>
        </div>
        <p className="muted small">
          {mode === 'interview'
            ? 'The agent asks a few questions first, then hands a finished prompt to a fresh build session.'
            : 'Skip the interview and start building right away.'}
        </p>
        <button onClick={handleNewSession} disabled={creating}>
          {creating ? 'Creating…' : '+ New session'}
        </button>
      </div>
    </main>
  );
}
