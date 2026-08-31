import { Router } from 'express';
import { supabaseAdmin } from '../supabaseAdmin.js';
import { runTurn } from '../agent/loop.js';
import { runInterviewTurn } from '../agent/interviewLoop.js';
import { generateSessionTitle } from '../agent/titleGenerator.js';
import { defaultEffortFor } from '../config.js';
import { getProviderSync, listProvidersSync } from '../services/settingsStore.js';

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
  const { data: existing, error: fetchError } = await supabaseAdmin
    .from('sessions')
    .select('*')
    .eq('id', req.params.id)
    .single();
  if (fetchError || !existing) return res.status(404).json({ error: 'Session not found.' });

  const patch = {};
  if (typeof req.body.title === 'string' && req.body.title.trim()) patch.title = req.body.title.trim();

  // provider and reasoning_effort are validated together, since a provider switch can
  // invalidate the session's current effort (a different provider may support
  // different levels, or none at all).
  let provider = getProviderSync(existing.provider) || listProvidersSync()[0] || null;

  if (req.body.provider !== undefined) {
    const requested = getProviderSync(req.body.provider);
    if (!requested) {
      return res.status(400).json({ error: `Unknown provider '${req.body.provider}'. Add it in Settings first.` });
    }
    patch.provider = req.body.provider;
    provider = requested;
    if (!provider.reasoningEfforts.includes(existing.reasoning_effort)) {
      patch.reasoning_effort = defaultEffortFor(provider);
    }
  }

  if (!provider) {
    return res.status(400).json({ error: 'No model providers configured — add one in Settings first.' });
  }

  if (req.body.reasoning_effort !== undefined) {
    const efforts = provider.reasoningEfforts;
    if (req.body.reasoning_effort === null) {
      if (efforts.length) {
        return res.status(400).json({ error: `Provider '${provider.id}' requires a reasoning_effort (one of: ${efforts.join(', ')}).` });
      }
      patch.reasoning_effort = null;
    } else if (!efforts.includes(req.body.reasoning_effort)) {
      return res.status(400).json({
        error: `reasoning_effort must be one of: ${efforts.length ? efforts.join(', ') : '(this provider takes no reasoning_effort)'}`,
      });
    } else {
      patch.reasoning_effort = req.body.reasoning_effort;
    }
  }

  if (Object.keys(patch).length === 0) return res.status(400).json({ error: 'Nothing to update.' });

  const { data, error } = await supabaseAdmin.from('sessions').update(patch).eq('id', req.params.id).select().single();
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

// The core endpoint: POST { text, reasoning_effort? } → text/event-stream held open
// for the whole turn (build spec §9). reasoning_effort is optional per-request — if
// omitted, the session's stored default is used; if provided and different, it
// becomes the session's new default going forward. Which agent loop actually runs
// depends on session.kind: 'interview' routes to the prompt-maker agent, 'build' to
// the main coding agent — same endpoint, same SSE contract, different agent entirely.
router.post('/:id/messages', async (req, res) => {
  const { text, reasoning_effort } = req.body;
  if (!text || !text.trim()) return res.status(400).json({ error: 'text is required' });

  const { data: session, error: sessionError } = await supabaseAdmin
    .from('sessions')
    .select('*')
    .eq('id', req.params.id)
    .single();
  if (sessionError || !session) return res.status(404).json({ error: 'Session not found.' });

  if (session.kind === 'interview' && session.completed_at) {
    return res.status(409).json({
      error: 'This prompt-maker session already generated a build session — continue the conversation there instead.',
    });
  }

  const { data: project, error: projectError } = await supabaseAdmin
    .from('projects')
    .select('*')
    .eq('id', session.project_id)
    .single();
  if (projectError || !project) return res.status(404).json({ error: 'Project not found.' });

  const provider = getProviderSync(session.provider);
  if (!provider) {
    return res.status(500).json({
      error: `Session is set to unknown provider '${session.provider}'. It may have been removed in Settings — switch this session to a configured provider.`,
    });
  }

  let effort = session.reasoning_effort;
  if (reasoning_effort !== undefined && reasoning_effort !== effort) {
    if (provider.reasoningEfforts.length && !provider.reasoningEfforts.includes(reasoning_effort)) {
      return res.status(400).json({ error: `reasoning_effort must be one of: ${provider.reasoningEfforts.join(', ')}` });
    }
    effort = provider.reasoningEfforts.length ? reasoning_effort : null;
    await supabaseAdmin.from('sessions').update({ reasoning_effort: effort }).eq('id', session.id);
  }

  // Checked before the turn runs (the turn itself saves the user's message as its
  // first step) — determines whether this session is eligible for auto-naming below.
  // A count query rather than a full select: we only need to know whether it's zero.
  const { count: priorMessageCount, error: countError } = await supabaseAdmin
    .from('messages')
    .select('id', { count: 'exact', head: true })
    .eq('session_id', session.id);
  if (countError) return res.status(500).json({ error: countError.message });
  const isFirstMessage = (priorMessageCount || 0) === 0;

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
    if (session.kind === 'interview') {
      await runInterviewTurn({ project, session, userText: text, provider, effort, sse });
    } else {
      await runTurn({ project, session, userText: text, provider, effort, sse });
    }

    // Auto-name the session from its first message, the same way most chat products
    // title a new conversation — only ever on the first turn, and only if nothing
    // (manual rename, an earlier attempt) already gave it a real title. Runs after
    // the turn's own 'done'/'handoff' event so it never delays the visible response;
    // failure here just leaves the session's default title in place.
    if (isFirstMessage && (!session.title || session.title === 'New session')) {
      try {
        const title = await generateSessionTitle({ provider, userText: text, effort });
        if (title) {
          await supabaseAdmin.from('sessions').update({ title }).eq('id', session.id);
          sse.send('session_title', { title });
        }
      } catch (err) {
        console.error(`Title generation failed for session ${session.id}:`, err);
      }
    }
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
