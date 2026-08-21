import { Router } from 'express';
import { supabaseAdmin } from '../supabaseAdmin.js';

const router = Router();

router.get('/', async (_req, res) => {
  const { data, error } = await supabaseAdmin.from('projects').select('*').order('created_at', { ascending: false });
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

router.post('/', async (req, res) => {
  const { name, github_repo } = req.body;
  if (!name || !name.trim()) return res.status(400).json({ error: 'name is required' });

  const insert = { name: name.trim() };
  if (github_repo && github_repo.trim()) insert.github_repo = github_repo.trim();

  const { data, error } = await supabaseAdmin.from('projects').insert(insert).select().single();
  if (error) return res.status(500).json({ error: error.message });
  res.status(201).json(data);
});

router.get('/:id', async (req, res) => {
  const { data, error } = await supabaseAdmin.from('projects').select('*').eq('id', req.params.id).single();
  if (error || !data) return res.status(404).json({ error: 'Project not found.' });
  res.json(data);
});

router.get('/:id/sessions', async (req, res) => {
  const { data, error } = await supabaseAdmin
    .from('sessions')
    .select('*')
    .eq('project_id', req.params.id)
    .order('updated_at', { ascending: false });
  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

router.post('/:id/sessions', async (req, res) => {
  const title = (req.body.title || '').trim() || 'New session';
  const { data, error } = await supabaseAdmin
    .from('sessions')
    .insert({ project_id: req.params.id, title })
    .select()
    .single();
  if (error) return res.status(500).json({ error: error.message });
  res.status(201).json(data);
});

export default router;
