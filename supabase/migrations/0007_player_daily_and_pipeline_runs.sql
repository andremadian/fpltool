-- Migration 0007 — daily price/news time series + pipeline run log
-- (Phase 3A, item 2 — see docs/EXPANSION_PLAN.md)
--
-- player_daily: one row per (season, player, calendar date), written by the
-- new daily light run (`fpl_engine.py --daily`, one bootstrap HTTP call).
-- Captures the signals the weekly cadence structurally cannot see: price
-- moves, ownership momentum, and availability news as they change day to
-- day. ~840 rows/day ≈ ~300k/season — trivial for Postgres.
--
-- pipeline_runs: one row per engine run (any mode, any outcome). This is
-- what the Phase 3B agent's get_data_freshness() tool reads, and it turns
-- "did Friday's run work?" into a query. Inserted even for off-season
-- early-exit runs so silence in this table always means "the run never
-- happened" — the June–July 2026 silent-failure class.
--
-- RLS stays off — global/operational data, consistent with decision #5.
-- Apply via Supabase SQL Editor after 0006.

create table if not exists player_daily (
  season text not null,
  player_id int not null,
  as_of_date date not null,
  price numeric(3,1),
  ownership numeric(4,1),
  transfers_in_event int default 0,
  transfers_out_event int default 0,
  cost_change_event numeric(3,1) default 0,
  status text,
  news text,
  chance_of_playing_next_round int,
  form numeric(4,2),
  total_points int default 0,
  captured_at timestamptz default now(),
  primary key (season, player_id, as_of_date)
);

create index if not exists player_daily_date_idx on player_daily (as_of_date);
create index if not exists player_daily_player_idx on player_daily (season, player_id);

create table if not exists pipeline_runs (
  id bigint generated always as identity primary key,
  engine text not null,            -- 'fpl_engine' | 'fpl_engine --daily' | 'fpl_user_engine'
  season text,
  gw int,
  rows_written int default 0,
  duration_seconds numeric(7,1),
  status text not null,            -- 'success' | 'failed' | 'skipped_offseason' | 'skipped_no_config'
  detail text,                     -- error message on failure, summary otherwise
  ran_at timestamptz default now()
);

create index if not exists pipeline_runs_engine_idx on pipeline_runs (engine, ran_at desc);
