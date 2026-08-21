import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api.js';
import { supabase } from '../supabaseClient.js';

export default function ProjectList() {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [name, setName] = useState('');
  const [githubRepo, setGithubRepo] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    refresh();
  }, []);

  function refresh() {
    api
      .listProjects()
      .then(setProjects)
      .catch((err) => setError(err.message));
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await api.createProject(name.trim(), githubRepo.trim());
      setName('');
      setGithubRepo('');
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Projects</h1>
        <button className="ghost" onClick={() => supabase.auth.signOut()}>
          Sign out
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {projects === null ? (
        <p className="muted">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="muted">No projects yet.</p>
      ) : (
        <ul className="list">
          {projects.map((p) => (
            <li key={p.id}>
              <Link to={`/project/${p.id}`}>{p.name}</Link>
              <span className="muted"> {p.github_repo || '(no repo yet)'}</span>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleCreate} className="stack card">
        <h2>New project</h2>
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label>
          Existing repo (optional)
          <input
            value={githubRepo}
            onChange={(e) => setGithubRepo(e.target.value)}
            placeholder="owner/repo — leave blank to create one fresh"
          />
        </label>
        <button type="submit" disabled={creating}>
          {creating ? 'Creating…' : '+ New project'}
        </button>
      </form>
    </main>
  );
}
