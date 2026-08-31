import crypto from 'node:crypto';
import { supabaseAdmin } from '../supabaseAdmin.js';

/**
 * BYOK settings store. Model providers (id, base URL, API key, model, reasoning
 * efforts) and other service secrets (GitHub token, Vercel token, Tavily key, ...)
 * live in Supabase (`providers` / `secrets` tables — see sql/003_settings.sql)
 * instead of `backend/.env`, so they can be added, edited, and rotated from the
 * Settings page without redeploying.
 *
 * Values are encrypted at rest (AES-256-GCM) under a key derived from the
 * SETTINGS_ENCRYPTION_KEY env var — that's the one secret still required in the
 * environment; it exists to protect everything else, the same way any BYOK system
 * needs one root key. Losing it means every saved provider/secret has to be re-entered.
 *
 * The harness is a single long-lived Node process (a real Render web service, not
 * serverless), so an in-memory cache is safe: it's populated at boot (initSettings,
 * called once from index.js before the server starts accepting requests) and
 * refreshed after every write made through this module. Don't edit the `providers` /
 * `secrets` tables directly in Supabase — the running process won't see it until
 * restart.
 */

let encryptionKey = null;

function ensureEncryptionKey() {
  if (encryptionKey) return encryptionKey;
  const secret = process.env.SETTINGS_ENCRYPTION_KEY;
  if (!secret) {
    console.error(
      'Missing required env var: SETTINGS_ENCRYPTION_KEY. This encrypts every ' +
        'provider/API key saved in Settings — generate one with `openssl rand -hex 32` ' +
        "and set it before starting the backend. It's the one secret that still has to " +
        'live in the environment; every model-provider key and every other API key ' +
        '(GitHub, Vercel, Tavily, ...) now lives in Settings instead.',
    );
    process.exit(1);
  }
  encryptionKey = crypto.createHash('sha256').update(secret).digest();
  return encryptionKey;
}

function encrypt(plaintext) {
  const key = ensureEncryptionKey();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const enc = Buffer.concat([cipher.update(String(plaintext), 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, enc]).toString('base64');
}

function decrypt(payload) {
  const key = ensureEncryptionKey();
  const raw = Buffer.from(payload, 'base64');
  const iv = raw.subarray(0, 12);
  const tag = raw.subarray(12, 28);
  const enc = raw.subarray(28);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(enc), decipher.final()]).toString('utf8');
}

let cache = { providers: new Map(), secrets: new Map() };

function rowToProvider(row) {
  return {
    id: row.id,
    label: row.label,
    baseUrl: row.base_url.replace(/\/+$/, ''),
    apiKey: decrypt(row.api_key_encrypted),
    model: row.model,
    reasoningEfforts: row.reasoning_efforts || [],
    updatedAt: row.updated_at,
  };
}

/** Reload the in-memory cache from Supabase. Called at boot and after every write. */
export async function loadAll() {
  const [{ data: providerRows, error: pErr }, { data: secretRows, error: sErr }] = await Promise.all([
    supabaseAdmin.from('providers').select('*'),
    supabaseAdmin.from('secrets').select('*'),
  ]);
  if (pErr) throw new Error(`Failed to load providers from Supabase: ${pErr.message}`);
  if (sErr) throw new Error(`Failed to load secrets from Supabase: ${sErr.message}`);

  const providers = new Map();
  for (const row of providerRows || []) providers.set(row.id, rowToProvider(row));

  const secrets = new Map();
  for (const row of secretRows || []) {
    secrets.set(row.key, { key: row.key, label: row.label, value: decrypt(row.value_encrypted), updatedAt: row.updated_at });
  }

  cache = { providers, secrets };
}

/**
 * Boot-time setup: loads the cache, then — only if the tables are completely empty,
 * i.e. this Settings page has never been touched — does a one-time import of
 * whatever the old .env-based config already had. That way upgrading an existing
 * deployment doesn't break it. After this runs once, .env values for providers/
 * GITHUB_TOKEN/VERCEL_TOKEN/VERCEL_TEAM_ID/TAVILY_API_KEY are never read again —
 * everything from here on is managed from the Settings page.
 */
export async function initSettings() {
  ensureEncryptionKey();
  await loadAll();

  const freshProviders = cache.providers.size === 0;
  const freshSecrets = cache.secrets.size === 0;

  if (freshProviders && process.env.DEEPSEEK_API_KEY) {
    await upsertProvider({
      id: 'deepseek',
      label: 'DeepSeek V4 Flash',
      baseUrl: process.env.DEEPSEEK_BASE_URL || 'https://api.deepseek.com',
      apiKey: process.env.DEEPSEEK_API_KEY,
      model: process.env.DEEPSEEK_MODEL || 'deepseek-v4-flash',
      reasoningEfforts: ['low', 'high', 'max'],
    });
    console.log("Settings: imported 'deepseek' provider from legacy .env vars (one-time). Manage it from the Settings page from now on.");
  }
  if (freshProviders && process.env.CUSTOM_BASE_URL && process.env.CUSTOM_API_KEY) {
    const effortsRaw = (process.env.CUSTOM_REASONING_EFFORTS || '').trim();
    await upsertProvider({
      id: 'custom',
      label: process.env.CUSTOM_LABEL || 'Custom',
      baseUrl: process.env.CUSTOM_BASE_URL,
      apiKey: process.env.CUSTOM_API_KEY,
      model: process.env.CUSTOM_MODEL || 'gpt-5',
      reasoningEfforts: effortsRaw ? effortsRaw.split(',').map((s) => s.trim()).filter(Boolean) : [],
    });
    console.log("Settings: imported 'custom' provider from legacy .env vars (one-time). Manage it from the Settings page from now on.");
  }

  if (freshSecrets) {
    const legacy = [
      ['github_token', process.env.GITHUB_TOKEN, 'GitHub token'],
      ['vercel_token', process.env.VERCEL_TOKEN, 'Vercel token'],
      ['vercel_team_id', process.env.VERCEL_TEAM_ID, 'Vercel team ID'],
      ['tavily_api_key', process.env.TAVILY_API_KEY, 'Tavily API key'],
    ];
    for (const [key, value, label] of legacy) {
      if (!value) continue;
      await setSecret(key, value, label);
      console.log(`Settings: imported '${key}' from legacy .env vars (one-time). Manage it from the Settings page from now on.`);
    }
  }
}

// ---- Providers ----

export function listProvidersSync() {
  return Array.from(cache.providers.values());
}

export function getProviderSync(id) {
  return cache.providers.get(id) || null;
}

export async function upsertProvider({ id, label, baseUrl, apiKey, model, reasoningEfforts }) {
  if (!id || !/^[a-z0-9][a-z0-9-_]*$/i.test(id)) {
    throw new Error("Provider id must be alphanumeric (dashes/underscores OK), e.g. 'openai' or 'my-gateway'.");
  }
  const existing = cache.providers.get(id);
  const resolvedKey = apiKey ? apiKey : existing?.apiKey;
  if (!resolvedKey) throw new Error('apiKey is required (leave blank on an edit to keep the existing key).');
  const resolvedBaseUrl = baseUrl || existing?.baseUrl;
  if (!resolvedBaseUrl) throw new Error('baseUrl is required.');

  const row = {
    id,
    label: label || existing?.label || id,
    base_url: resolvedBaseUrl.replace(/\/+$/, ''),
    api_key_encrypted: encrypt(resolvedKey),
    model: model || existing?.model || 'gpt-5',
    reasoning_efforts: Array.isArray(reasoningEfforts) ? reasoningEfforts : existing?.reasoningEfforts || [],
    updated_at: new Date().toISOString(),
  };
  const { error } = await supabaseAdmin.from('providers').upsert(row);
  if (error) throw new Error(`Failed to save provider: ${error.message}`);
  await loadAll();
  return getProviderSync(id);
}

export async function deleteProvider(id) {
  const { error } = await supabaseAdmin.from('providers').delete().eq('id', id);
  if (error) throw new Error(`Failed to delete provider: ${error.message}`);
  await loadAll();
}

// ---- Secrets (GitHub token, Vercel token, Tavily key, or anything else) ----

export function getSecretSync(key) {
  return cache.secrets.get(key)?.value ?? null;
}

export function listSecretsSync() {
  return Array.from(cache.secrets.values()).map((s) => ({
    key: s.key,
    label: s.label,
    hasValue: !!s.value,
    updatedAt: s.updatedAt,
  }));
}

// value is optional when the key already exists — leaving it blank on an edit keeps
// whatever's currently saved (same pattern as upsertProvider's apiKey), so the
// Settings page can offer "leave blank to keep it" without a separate code path.
export async function setSecret(key, value, label) {
  if (!key || !key.trim()) throw new Error('key is required.');
  const existing = cache.secrets.get(key);
  const resolvedValue = value ? value : existing?.value;
  if (!resolvedValue) throw new Error('value is required.');
  const row = {
    key: key.trim(),
    label: label || existing?.label || key,
    value_encrypted: encrypt(resolvedValue),
    updated_at: new Date().toISOString(),
  };
  const { error } = await supabaseAdmin.from('secrets').upsert(row);
  if (error) throw new Error(`Failed to save secret: ${error.message}`);
  await loadAll();
}

export async function deleteSecret(key) {
  const { error } = await supabaseAdmin.from('secrets').delete().eq('key', key);
  if (error) throw new Error(`Failed to delete secret: ${error.message}`);
  await loadAll();
}

function requireSecret(key, humanName) {
  const value = getSecretSync(key);
  if (!value) throw new Error(`${humanName} is not set — add it in Settings (key: ${key}).`);
  return value;
}

export const getGithubToken = () => requireSecret('github_token', 'GitHub token');
export const getVercelToken = () => requireSecret('vercel_token', 'Vercel token');
export const getVercelTeamId = () => getSecretSync('vercel_team_id'); // optional, no throw
export const getTavilyApiKey = () => requireSecret('tavily_api_key', 'Tavily API key');
