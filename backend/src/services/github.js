import { getGithubToken } from './settingsStore.js';

const API = 'https://api.github.com';

async function gh(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${getGithubToken()}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    const err = new Error(`GitHub ${options.method || 'GET'} ${path} → ${res.status}: ${body.slice(0, 500)}`);
    err.status = res.status;
    throw err;
  }

  // DELETE on the contents endpoint returns a body; some other calls return 204.
  if (res.status === 204) return null;
  return res.json();
}

export async function listTree(repo, branch) {
  const data = await gh(`/repos/${repo}/git/trees/${encodeURIComponent(branch)}?recursive=1`);
  return (data.tree || [])
    .filter((entry) => entry.type === 'blob')
    .map((entry) => entry.path);
}

export async function readFile(repo, path, branch) {
  const data = await gh(`/repos/${repo}/contents/${encodeURIComponent(path)}?ref=${encodeURIComponent(branch)}`);
  if (Array.isArray(data)) {
    throw new Error(`'${path}' is a directory, not a file.`);
  }
  const content = Buffer.from(data.content, data.encoding || 'base64').toString('utf-8');
  return { content, sha: data.sha };
}

async function getShaIfExists(repo, path, branch) {
  try {
    const { sha } = await readFile(repo, path, branch);
    return sha;
  } catch (err) {
    if (err.status === 404) return null; // genuinely doesn't exist yet — fine, this is a create
    throw err; // auth failure, rate limit, etc. — must not be silently treated as "new file"
  }
}

export async function writeFile(repo, path, content, commitMessage, branch) {
  const sha = await getShaIfExists(repo, path, branch);
  const body = {
    message: commitMessage,
    content: Buffer.from(content, 'utf-8').toString('base64'),
    branch,
    ...(sha ? { sha } : {}),
  };
  const data = await gh(`/repos/${repo}/contents/${encodeURIComponent(path)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  return { commitSha: data.commit?.sha, path };
}

export async function deleteFile(repo, path, commitMessage, branch) {
  const sha = await getShaIfExists(repo, path, branch);
  if (!sha) {
    throw new Error(`Cannot delete '${path}': it doesn't exist on branch '${branch}'.`);
  }
  const data = await gh(`/repos/${repo}/contents/${encodeURIComponent(path)}`, {
    method: 'DELETE',
    body: JSON.stringify({ message: commitMessage, sha, branch }),
  });
  return { commitSha: data.commit?.sha, path };
}

export async function createRepo(name, isPrivate = true) {
  const data = await gh('/user/repos', {
    method: 'POST',
    body: JSON.stringify({ name, private: isPrivate, auto_init: true }),
  });
  return { fullName: data.full_name, defaultBranch: data.default_branch || 'main' };
}
