-- 0014: weekly brief output table.
-- One row per generated brief; the PWA reads the latest row. Idempotent.

create table if not exists weekly_brief (
  id           bigint generated always as identity primary key,
  season       text not null,
  gw           int not null,
  generated_at timestamptz not null default now(),
  mode         text not null,
  payload      jsonb not null
);

create index if not exists weekly_brief_generated_at_idx
  on weekly_brief (generated_at desc);

alter table weekly_brief enable row level security;

do $$
begin
  create policy "owner read" on weekly_brief for select to authenticated
    using ((select auth.uid()) = '8c4afa9c-e4ed-4b45-9f9e-02f347944ecb'::uuid);
exception when duplicate_object then null;   -- re-runnable
end $$;

-- Read-only from the browser; the engine writes with the service role.
revoke insert, update, delete on weekly_brief from authenticated;
revoke all on weekly_brief from anon;
