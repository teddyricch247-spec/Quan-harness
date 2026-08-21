import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../lib/api.js';

export default function SessionList() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState(null);
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);

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

  async function handleNewSession() {
    setCreating(true);
    setError(null);
    try {
      const session = await api.createSession(projectId, 'New session');
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
              <Link to={`/project/${projectId}/session/${s.id}`}>{s.title}</Link>
              <span className="muted"> {new Date(s.updated_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}

      <button onClick={handleNewSession} disabled={creating}>
        {creating ? 'Creating…' : '+ New session'}
      </button>
    </main>
  );
}
