import express from 'express';
import cors from 'cors';
import { config } from './config.js';
import { requireAuth } from './auth/middleware.js';
import projectsRouter from './routes/projects.js';
import sessionsRouter from './routes/sessions.js';
import metaRouter from './routes/meta.js';

const app = express();

app.use(cors({ origin: config.frontendOrigin }));
app.use(express.json({ limit: '2mb' }));

app.get('/health', (_req, res) => res.json({ ok: true }));

app.use('/api/projects', requireAuth, projectsRouter);
app.use('/api/sessions', requireAuth, sessionsRouter);
app.use('/api/meta', requireAuth, metaRouter);

app.use((req, res) => {
  res.status(404).json({ error: 'Not found.' });
});

// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error(err);
  if (res.headersSent) return; // an SSE stream may have already started writing
  res.status(500).json({ error: 'Internal server error.' });
});

app.listen(config.port, () => {
  console.log(`Harness backend listening on :${config.port}`);
});
