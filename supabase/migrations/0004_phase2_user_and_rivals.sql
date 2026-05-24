-- ============================================
-- PHASE 2 — USER & RIVALS DATA INGESTION
-- ============================================
-- Adds tables for tracking my own FPL squad and the squads of
-- rivals across my mini-leagues. Populated by fpl_user_engine.py.
--
-- These tables intentionally do NOT use Supabase Auth (no FK to
-- auth.users) — Phase 2 runs as a personal research tool without
-- login. The existing users / user_rivals scaffold tables from
-- migration 0001 remain empty and wait for Phase 3+.
-- ============================================

-- Configuration: which leagues do I want to track?
-- Populated manually via Supabase Studio SQL editor — insert one row
-- per league. The Python script reads this on each run.
create table tracked_leagues (
  league_id int primary key,
  league_name text,
  my_fpl_team_id int not null,
  notes text,
  added_at timestamptz default now()
);

-- My squad, snapshotted per gameweek. One row per (fpl_team_id, gw).
create table user_team_snapshots (
  fpl_team_id int not null,
  gw int not null,
  player_ids int[] not null,
  captain_id int,
  vice_captain_id int,
  chip_used text,
  bench_order int[],
  transfers_made int default 0,
  transfer_cost int default 0,
  event_points int,
  event_rank int,
  overall_rank int,
  bank numeric(3,1),
  team_value numeric(4,1),
  refreshed_at timestamptz default now(),
  primary key (fpl_team_id, gw)
);

create index on user_team_snapshots (gw);

-- Mini-league standings, refreshed per run.
-- One row per (league_id, rival_fpl_team_id).
create table league_rivals (
  league_id int references tracked_leagues(league_id) on delete cascade,
  rival_fpl_team_id int not null,
  rival_name text,
  rival_player_name text,
  total_points int,
  league_rank int,
  last_rank int,
  refreshed_at timestamptz default now(),
  primary key (league_id, rival_fpl_team_id)
);

create index on league_rivals (rival_fpl_team_id);

-- Rivals' squads per gameweek. Same shape as user_team_snapshots
-- minus the personal financial fields (bank, team_value, ranks).
create table rival_team_snapshots (
  rival_fpl_team_id int not null,
  gw int not null,
  player_ids int[] not null,
  captain_id int,
  vice_captain_id int,
  chip_used text,
  bench_order int[],
  transfers_made int default 0,
  transfer_cost int default 0,
  event_points int,
  refreshed_at timestamptz default now(),
  primary key (rival_fpl_team_id, gw)
);

create index on rival_team_snapshots (gw);
create index on rival_team_snapshots (rival_fpl_team_id, gw);
