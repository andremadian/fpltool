-- Migration 0012 — player_season_stats season-boundary fix (Phase 3C)
--
-- Same root cause as 0011 (decision #10/#13): the 0008 player_season_stats
-- view summed player_history but joined it to the live players_master by id,
-- and read xg/xa/form/ownership from that snapshot. At the 2025/26→2026/27
-- rollover the snapshot holds re-issued IDs, so the Chart maker and the
-- Stats/Transfers row-expand (both read this view) showed mis-attributed
-- names and pre-season-reset expected/live stats.
--
-- Fix (mirrors 0011): anchor on the latest finished-fixture season, resolve
-- identity from players_season_archive when that season is archived (else the
-- live players_master), and sum every stat — including xg/xa/xgi/xgc — from
-- player_history for the anchor season. Live-only fields (ownership, form,
-- status, chance_of_playing_next_round) are NULL for a completed season and
-- populate once the current season is under way. Output columns/order are
-- unchanged, so the PWA's PlayerSeasonStats interface and the Chart maker's
-- axis list are untouched (ownership just becomes nullable).
--
-- security_invoker + authenticated grant re-applied (loophole #19).

drop view if exists player_season_stats;

create view player_season_stats
with (security_invoker = on) as
with anchor as (
  select max(season) as season from fixtures where finished = true
),
identity as (
  select a.id as player_id, a.web_name, a.team_id, a.position, a.price,
         null::numeric as ownership, null::numeric as form,
         null::text as status, null::int as chance_of_playing_next_round
  from players_season_archive a
  where a.season = (select season from anchor)
  union all
  select pm.id, pm.web_name, pm.team_id, pm.position, pm.price,
         pm.ownership, pm.form, pm.status, pm.chance_of_playing_next_round
  from players_master pm
  where not exists (
    select 1 from players_season_archive x where x.season = (select season from anchor)
  )
),
agg as (
  select ph.player_id,
         sum(ph.goals)              as goals,
         sum(ph.assists)            as assists,
         sum(ph.goals + ph.assists) as goal_involvements,
         sum(ph.minutes)            as minutes,
         sum(ph.total_points)       as total_points,
         sum(ph.bps)                as bps,
         sum(ph.cbit)               as cbit,
         sum(ph.xg)                 as xg,
         sum(ph.xa)                 as xa,
         sum(ph.xgi)                as xgi,
         sum(ph.xgc)                as xgc
  from player_history ph
  where ph.season = (select season from anchor)
  group by ph.player_id
)
select
  (select season from anchor)   as season,
  i.player_id,
  i.web_name,
  i.team_id,
  i.position,
  i.price,
  i.ownership,
  a.xg::numeric(6,2)            as xg,
  a.xa::numeric(6,2)            as xa,
  a.xgi::numeric(6,2)           as xgi,
  a.xgc::numeric(6,2)           as xgc,
  i.form,
  i.status,
  i.chance_of_playing_next_round,
  a.goals,
  a.assists,
  a.goal_involvements,
  a.minutes,
  a.total_points,
  a.bps,
  a.cbit
from agg a
join identity i on i.player_id = a.player_id;

grant select on player_season_stats to authenticated;
