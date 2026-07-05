-- ============================================
-- 0005 — Season-aware time series (season rollover)
-- ============================================
-- FPL re-issues player IDs, team IDs (1-20) and fixture IDs every
-- season. Without a season discriminator, the first 2026/27 engine
-- run would upsert new-season rows into tables whose keys still
-- mean 2025/26 players/teams/fixtures — silently blending two
-- seasons under reused IDs.
--
-- This migration:
--   1. Adds a `season` column (text, e.g. '2025/26') to the four
--      time-series tables and backfills existing rows as '2025/26'.
--   2. Rebuilds each primary key to include season.
--   3. Recreates the team_history view with season.
--   4. Creates identity archive tables and snapshots the final
--      2025/26 players_master + teams into them. Next season's
--      ingestion overwrites both snapshot tables with re-issued
--      IDs, so without the archive, historical rows lose their
--      names ("who was player 233 in 2025/26?").
--
-- Apply BEFORE the first 2026/27 engine run. Both engines stamp
-- `season` on every row they write from this migration onward —
-- they will fail against a database that hasn't applied this.
--
-- Known limitation (accepted): team_history and any join from a
-- historical season to players_master / teams resolves names via
-- the CURRENT season's snapshot. For historical seasons, join
-- players_season_archive / teams_season_archive instead. The
-- curated queries in sql/queries/ all filter to the latest season,
-- so they are unaffected.
-- ============================================

-- 1. player_history — PK (season, player_id, gw)
alter table player_history add column season text;
update player_history set season = '2025/26';
alter table player_history alter column season set not null;
alter table player_history drop constraint player_history_pkey;
alter table player_history add primary key (season, player_id, gw);

-- 2. fixtures — PK (season, id); FPL fixture IDs restart each season
alter table fixtures add column season text;
update fixtures set season = '2025/26';
alter table fixtures alter column season set not null;
alter table fixtures drop constraint fixtures_pkey;
alter table fixtures add primary key (season, id);

-- 3. user_team_snapshots — PK (season, fpl_team_id, gw)
alter table user_team_snapshots add column season text;
update user_team_snapshots set season = '2025/26';
alter table user_team_snapshots alter column season set not null;
alter table user_team_snapshots drop constraint user_team_snapshots_pkey;
alter table user_team_snapshots add primary key (season, fpl_team_id, gw);

-- 4. rival_team_snapshots — PK (season, rival_fpl_team_id, gw)
alter table rival_team_snapshots add column season text;
update rival_team_snapshots set season = '2025/26';
alter table rival_team_snapshots alter column season set not null;
alter table rival_team_snapshots drop constraint rival_team_snapshots_pkey;
alter table rival_team_snapshots add primary key (season, rival_fpl_team_id, gw);

-- 5. team_history view, now grouped by season as well
drop view team_history;

create view team_history as
select
  ph.season,
  pm.team_id,
  t.name as team_name,
  ph.gw,
  sum(ph.goals) as total_goals,
  sum(ph.xg) as total_xg,
  sum(ph.xa) as total_xa,
  max(ph.xgc) as team_xgc,
  sum(ph.clean_sheets) as cs_count
from player_history ph
join players_master pm on pm.id = ph.player_id
join teams t on t.id = pm.team_id
group by ph.season, pm.team_id, t.name, ph.gw;

-- 6. Identity archives — who did each (season, id) refer to?
-- Populated once per season: here for 2025/26, and automatically by
-- fpl_engine.py at each future season end (when every GW is finished).
-- RLS deliberately off, same as the other public FPL data tables.

create table players_season_archive (
  season text not null,
  id int not null,
  web_name text not null,
  team_id int,
  position text,
  price numeric(3,1),
  total_points int,
  archived_at timestamptz default now(),
  primary key (season, id)
);

insert into players_season_archive (season, id, web_name, team_id, position, price, total_points)
select '2025/26', id, web_name, team_id, position, price, total_points
from players_master;

create table teams_season_archive (
  season text not null,
  id int not null,
  name text not null,
  short_name text not null,
  archived_at timestamptz default now(),
  primary key (season, id)
);

insert into teams_season_archive (season, id, name, short_name)
select '2025/26', id, name, short_name
from teams;
