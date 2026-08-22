import { Router } from 'express';
import { config } from '../config.js';

const router = Router();

// Lets the frontend build its provider switcher without hardcoding provider ids —
// if only DeepSeek is configured, this returns a single-entry list and the frontend
// hides the switcher entirely (see ProviderSwitch.jsx).
router.get('/', (_req, res) => {
  const providers = Object.values(config.providers).map((p) => ({
    id: p.id,
    label: p.label,
    reasoningEfforts: p.reasoningEfforts,
  }));
  res.json({ providers });
});

export default router;
