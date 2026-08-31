import { Router } from 'express';
import {
  listProvidersSync,
  upsertProvider,
  deleteProvider,
  listSecretsSync,
  setSecret,
  deleteSecret,
} from '../services/settingsStore.js';

const router = Router();

// API keys never leave the backend once saved — the frontend only ever sees a
// masked preview (enough to recognize which key is saved) so Settings can show
// "saved" state without round-tripping the real value.
function maskKey(key) {
  if (!key) return null;
  return key.length <= 4 ? '••••' : `••••${key.slice(-4)}`;
}

// ---- Model providers ----

router.get('/providers', (_req, res) => {
  const providers = listProvidersSync().map((p) => ({
    id: p.id,
    label: p.label,
    baseUrl: p.baseUrl,
    model: p.model,
    reasoningEfforts: p.reasoningEfforts,
    apiKeyPreview: maskKey(p.apiKey),
    updatedAt: p.updatedAt,
  }));
  res.json({ providers });
});

// Upsert by id — id is the slug stored on sessions.provider (e.g. 'deepseek',
// 'openai', 'my-gateway'). apiKey is optional on an edit: leave it blank to keep
// whatever key is already saved (only rotate it when a new one is actually sent).
router.put('/providers/:id', async (req, res) => {
  try {
    const { label, baseUrl, apiKey, model, reasoningEfforts } = req.body;
    const efforts = typeof reasoningEfforts === 'string'
      ? reasoningEfforts.split(',').map((s) => s.trim()).filter(Boolean)
      : reasoningEfforts;
    const saved = await upsertProvider({ id: req.params.id, label, baseUrl, apiKey, model, reasoningEfforts: efforts });
    res.json({
      id: saved.id,
      label: saved.label,
      baseUrl: saved.baseUrl,
      model: saved.model,
      reasoningEfforts: saved.reasoningEfforts,
      apiKeyPreview: maskKey(saved.apiKey),
      updatedAt: saved.updatedAt,
    });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

router.delete('/providers/:id', async (req, res) => {
  try {
    await deleteProvider(req.params.id);
    res.status(204).end();
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

// ---- Other secrets (GitHub token, Vercel token, Tavily key, or anything else) ----

router.get('/secrets', (_req, res) => {
  res.json({ secrets: listSecretsSync() });
});

router.put('/secrets/:key', async (req, res) => {
  try {
    const { value, label } = req.body;
    await setSecret(req.params.key, value, label);
    res.status(204).end();
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

router.delete('/secrets/:key', async (req, res) => {
  try {
    await deleteSecret(req.params.key);
    res.status(204).end();
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

export default router;
