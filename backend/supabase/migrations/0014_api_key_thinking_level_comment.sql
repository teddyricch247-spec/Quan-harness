-- Comment-only. No data or schema change.
--
-- The column comment on api_keys.thinking_level was written (as "migration 0012")
-- before the single model was split into Kael Beta and Kael Pro Beta, and it
-- never said which model a pinned tier applies to. Every tier belongs to exactly
-- one model (kael-beta: low, high, max; kael-pro-beta: z-low, z-high), so a pin
-- applies on that model only; on the other model the key behaves as SDK. See
-- backend/app/kael_pipeline.py, _pinned_tier().

comment on column public.api_keys.thinking_level is
  'Pinned thinking tier for requests made with this key: NULL (SDK: the request decides) or a tier name from reasoning_tiers in backend/app/models/kael/config.py. A tier belongs to one model (kael-beta: low, high, max; kael-pro-beta: z-low, z-high), so a pin applies on that model only; on the other model the key acts as SDK. Added in migration 0013.';
