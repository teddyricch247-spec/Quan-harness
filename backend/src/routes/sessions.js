import { Router } from 'express';
import { supabaseAdmin } from '../supabaseAdmin.js';
import { runTurn } from '../agent/loop.js';
import { REASONING_EFFORTS } from '../config.js';

const router = Router();

router.get('/:id', async (req, res) => {
  const { data, error } = await supabaseAdmin.from('sessions').select('*').eq('id', req.params.id).single();
  if (error || !data) return res.status(404).json({ error: 'Session not found.' });
  res.json(data);
});

router.get('/:id/messages', async (req, res) => {
  const { data, error } = await supabaseAdmin
    .from('messages')
    .select('*')
    .eq('session_id', req.params.id)
    .order('created_at', { ascending: true });
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

router.patch('/:id', async (req, res) => {
  const patch = {};
  if (typeof req.body.title === 'string' && req.body.title.trim()) patch.title = req.body.title.trim();
  if (req.body.reasoning_effort) {
    if (!REASONING_EFFORTS.includes(req.body.reasoning_effort)) {
      return res.status(400).json({ error: `reasoning_effort must be one of: ${REASONING_EFFORTS.join(', ')}` });
    }
    patch.reasoning_effort = req.body.reasoning_effort;
  }
  if (Object.keys(patch).length === 0) return res.status(400).json({ error: 'Nothing to update.' });

  const { data, error } = await supabaseAdmin.from('sessions').update(patch).eq('id', req.params.id).select().single();
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

// The core endpoint: POST { text, reasoning_effort? } → text/event-stream held open
// for the whole turn (build spec §9). reasoning_effort is optional per-request — if
// omitted, the session's stored default is used; if provided and different, it
// becomes the session's new default going forward (the thinking switch applies to
// every call this turn makes, main agent and verifier alike).
router.post('/:id/messages', async (req, res) => {
  const { text, reasoning_effort } = req.body;
  if (!text || !text.trim()) return res.status(400).json({ error: 'text is required' });

  const { data: session, error: sessionError } = await supabaseAdmin
    .from('sessions')
    .select('*')
    .eq('id', req.params.id)
    .single();
  if (sessionError || !session) return res.status(404).json({ error: 'Session not found.' });

  const { data: project, error: projectError } = await supabaseAdmin
    .from('projects')
    .select('*')
    .eq('id', session.project_id)
    .single();
  if (projectError || !project) return res.status(404).json({ error: 'Project not found.' });

  let effort = session.reasoning_effort;
  if (reasoning_effort && reasoning_effort !== effort) {
    if (!REASONING_EFFORTS.includes(reasoning_effort)) {
      return res.status(400).json({ error: `reasoning_effort must be one of: ${REASONING_EFFORTS.join(', ')}` });
    }
    effort = reasoning_effort;
    await supabaseAdmin.from('sessions').update({ reasoning_effort: effort }).eq('id', session.id);
  }

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no', // disable proxy buffering (nginx/Render) so deltas arrive live
  });
  res.flushHeaders?.();

  // Disconnect tolerance (build spec §9): the handler is never aborted on client
  // disconnect. We just swallow write errors once the socket is gone — the loop
  // below keeps running and the final state still lands in Postgres regardless.
  const sse = {
    send(event, data) {
      try {
        res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      } catch {
        // client is gone; nothing to do here
      }
    },
  };

  try {
    await runTurn({ project, session, userText: text, effort, sse });
  } catch (err) {
    console.error(`Turn failed for session ${session.id}:`, err);
    sse.send('error', { message: err.message });
  } finally {
    try {
      res.end();
    } catch {
      // already closed
    }
  }
});

export default router;
