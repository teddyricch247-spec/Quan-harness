-- 0018_session_thinking_events.sql
-- Lets session_events hold the model's thinking text as its own event type ('thinking').
--
-- Why: the agent's thinking is now shown live while it works and kept afterwards as a collapsed "Thinking" block
-- (services/live_text.py saves one 'thinking' event per model call, just before the reply's own event). Without this
-- migration the save is refused by the CHECK constraint on session_events.event_type; the app logs that once and carries
-- on — the live thinking still shows, it just isn't kept.
--
-- How: the constraint is rebuilt from its CURRENT definition with 'thinking' added, instead of from a hard-coded list,
-- because this repo's migration history and the live database's differ (see docs/LING_THINKING_NOTES.md). If the
-- definition has an unexpected shape the block raises and changes nothing (a DO block is one transaction).
-- Additive and idempotent: running it twice is harmless. 'thinking' is never sent to the model (message_builder skips event
-- types it doesn't render), so nothing about prompts changes.

do $$
declare
    constraint_name text;
    definition text;
    rebuilt text;
begin
    select c.conname, pg_get_constraintdef(c.oid)
      into constraint_name, definition
      from pg_constraint c
     where c.conrelid = 'public.session_events'::regclass
       and c.contype = 'c'
       and pg_get_constraintdef(c.oid) like '%event_type%'
     limit 1;

    if definition is null then
        raise exception 'session_events has no CHECK constraint on event_type; nothing to extend (is this the right database?)';
    end if;

    if definition like '%''thinking''%' then
        raise notice 'session_events.event_type already allows ''thinking''; nothing to do';
        return;
    end if;

    rebuilt := replace(definition, '::text])', '::text, ''thinking''::text])');
    if rebuilt = definition then
        raise exception 'could not add ''thinking'' to the event_type constraint; its definition was: %', definition;
    end if;

    execute format('alter table public.session_events drop constraint %I', constraint_name);
    execute format('alter table public.session_events add constraint %I %s', constraint_name, rebuilt);
end
$$;
