import { config } from '../config.js';

const API = 'https://api.vercel.com';

function withTeam(path) {
  if (!config.vercelTeamId) return path;
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}teamId=${encodeURIComponent(config.vercelTeamId)}`;
}

async function vc(path, options = {}) {
  const res = await fetch(`${API}${withTeam(path)}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${config.vercelToken}`,
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Vercel ${options.method || 'GET'} ${path} → ${res.status}: ${body.slice(0, 500)}`);
  }
  return res.json();
}

// POST /v11/projects — confirmed current as of this build. If Vercel has revved this
// again by the time you read this, check https://vercel.com/docs/rest-api first.
export async function createProject(name, githubRepoFullName) {
  const data = await vc('/v11/projects', {
    method: 'POST',
    body: JSON.stringify({
      name,
      gitRepository: { type: 'github', repo: githubRepoFullName },
    }),
  });
  return { projectId: data.id, name: data.name };
}

export async function deploymentStatus(vercelProjectId) {
  const data = await vc(`/v6/deployments?projectId=${encodeURIComponent(vercelProjectId)}&limit=1`);
  const deployment = data.deployments?.[0];
  if (!deployment) return { state: 'none', message: 'No deployments found yet for this project.' };
  return {
    state: deployment.state || deployment.readyState,
    url: deployment.url ? `https://${deployment.url}` : null,
    createdAt: deployment.createdAt,
  };
}
