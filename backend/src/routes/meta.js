import { Router } from 'express';
import { listProvidersSync } from '../services/settingsStore.js';

const router = Router();

// Lets the frontend build its provider switcher without hardcoding provider ids —
// whatever's configured in Settings shows up here. A single-entry (or empty) list
// makes the switcher hide itself (see ProviderSwitch.jsx).
router.get('/', (_req, res) => {
  const providers = listProvidersSync().map((p) => ({
    id: p.id,
    label: p.label,
    reasoningEfforts: p.reasoningEfforts,
  }));
  res.json({ providers });
});

export default router;
