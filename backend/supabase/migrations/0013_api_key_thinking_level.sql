-- API keys: a per-key default thinking level.
--
-- Some agents (Cursor and similar) cannot send `reasoning_effort` at all, so
-- there was no way for them to use anything but the default tier. This adds a
-- per-key setting the owner chooses on the dashboard's API Keys page.
--
-- api_keys.thinking_level is NULL or one of the tier names in
-- backend/app/models/kael/config.py `reasoning_tiers`:
--   NULL                          "SDK": the request decides (today's behavior;
--                                 a request that names nothing gets the
--                                 default tier). Every existing key stays NULL.
--   low | high | max | z-low | z-high
--                                 pinned: every request from this key runs at
--                                 that tier and the request's own
--                                 reasoning_effort is ignored.
--
-- The tier names are deliberately NOT enforced by a check constraint here.
-- config.py is the single source of truth for them; a constraint would have to
-- be migrated every time a tier is added or renamed. The backend validates on
-- write (app/api_keys.py) and treats an unknown stored value as "SDK".
--
-- Additive and nullable: existing rows are untouched, old code ignores the
-- column. The backend also works if this is not applied yet
-- (app/api_keys.py retries without the column), so deploy order does not
-- matter; until it is applied, the dropdown on the dashboard cannot save.

alter table public.api_keys
  add column if not exists thinking_level text;

comment on column public.api_keys.thinking_level is
  'Pinned thinking tier for requests made with this key (a name from reasoning_tiers in backend/app/models/kael/config.py). NULL = SDK: the request decides. Added in migration 0013.';
