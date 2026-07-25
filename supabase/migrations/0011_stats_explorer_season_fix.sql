-- Migration 0011 — Stats Explorer season-boundary fix (Phase 3C)
--
-- PROBLEM (decision #10 in CLAUDE.md, hit for real at the 2025/26→2026/27
-- rollover): the 2026/27 FPL API is live, so `fixtures` already holds 380
-- unplayed 2026/27 rows and `players_master`/`teams` have been overwritten
-- with re-issued 2026/27 IDs — but no 2026/27 games have been played, so
-- `player_history`/`team_history` are still entirely 2025/26.
--   * The 0010 team views anchored on `max(season) from fixtures` = 2026/27,
--     which has 0 finished fixtures → every team metric was 0.
--   * The 0010 player views summed 2025/26 `player_history` but joined it to
--     the 2026/27 `players_master` by id. IDs are re-issued each season, so
--     names were mis-attributed (Haaland, whose 2025/26 id was 430 with 27
--     goals, showed 5 — the goals of whoever holds his *new* id 411).
--   * `form`/`ownership`/`ict` came from the 2026/27 pre-season snapshot, so
--     `form` was 0 for ~740 players.
--
-- FIX: anchor all four views on the latest season that actually has FINISHED
-- fixtures (2025/26 now; auto-advances to 2026/27 the moment GW1 is played).
-- Resolve player/team identity from the season archives when the anchor
-- season has been archived (a completed season), else from the live
-- players_master/teams (an in-progress current season). Compute every
-- counting/expected stat by summing `player_history` for the anchor season,
-- so the numbers are always keyed to the same season's IDs and never blend
-- seasons. Live-only fields (form/ownership/ict/status, team strength) exist
-- only for the current season and render as NULL ("—") for a completed one.
--
-- Column names/types are unchanged from 0010, so the PWA's TS interfaces and
-- column config are untouched. We drop+recreate (not create-or-replace)
-- because the underlying query structure changes; security_invoker and the
-- authenticated grant are re-applied per the loophole #19 convention.

drop view if exists player_explorer_season;
drop view if exists player_explorer_last5;
drop view if exists team_explorer_season;
drop view if exists team_explorer_last5;

-- ---------------------------------------------------------------------------
-- PLAYER — SEASON TOTALS
-- ---------------------------------------------------------------------------
create view player_explorer_season
with (security_invoker = on) as
with anchor as (
  select max(season) as season from fixtures where finished = true
),
identity as (
  -- Completed (archived) anchor season → correct historical identity.
  select a.id as player_id, a.web_name, a.team_id, a.position, a.price,
         null::numeric as ownership, null::numeric as form,
         null::numeric as ict_index, null::text as status
  from players_season_archive a
  where a.season = (select season from anchor)
  union all
  -- In-progress anchor season (not yet archived) → live snapshot.
  select pm.id, pm.web_name, pm.team_id, pm.position, pm.price,
         pm.ownership, pm.form, pm.ict_index, pm.status
  from players_master pm
  where not exists (
    select 1 from players_season_archive x where x.season = (select season from anchor)
  )
),
tname as (
  select ta.id as team_id, ta.short_name
  from teams_season_archive ta
  where ta.season = (select season from anchor)
  union all
  select tm.id, tm.short_name
  from teams tm
  where not exists (
    select 1 from teams_season_archive x where x.season = (select season from anchor)
  )
),
agg as (
  select ph.player_id,
         sum(ph.minutes)            as minutes,
         sum(ph.total_points)       as total_points,
         sum(ph.goals)              as goals,
         sum(ph.assists)            as assists,
         sum(ph.goals + ph.assists) as goal_involvements,
         sum(ph.clean_sheets)       as clean_sheets,
         sum(ph.cbit)               as cbit,
         sum(ph.bps)                as bps,
         sum(ph.xg)                 as xg,
         sum(ph.xa)                 as xa,
         sum(ph.xgi)                as xgi,
         sum(ph.xgc)                as xgc
  from player_history ph
  where ph.season = (select season from anchor)
  group by ph.player_id
)
select
  i.player_id,
  i.web_name,
  t.short_name                                                as team,
  i.position,
  i.price,
  i.status,
  i.ownership,
  a.minutes,
  a.total_points,
  case when a.minutes > 0
       then round(a.total_points::numeric * 90 / a.minutes, 2)
  end                                                         as points_per_90,
  case when i.price > 0
       then round(a.total_points::numeric / i.price, 2)
  end                                                         as points_per_million,
  a.goals,
  a.assists,
  a.goal_involvements,
  a.xg::numeric(6,2)                                          as xg,
  a.xa::numeric(6,2)                                          as xa,
  a.xgi::numeric(6,2)                                         as xgi,
  a.xgc::numeric(6,2)                                         as xgc,
  a.clean_sheets,
  a.cbit,
  a.bps,
  i.ict_index,
  i.form
from agg a
join identity i on i.player_id = a.player_id
left join tname t on t.team_id = i.team_id;

-- ---------------------------------------------------------------------------
-- PLAYER — LAST 5 GWs (minutes > 0) of the anchor season
-- ---------------------------------------------------------------------------
create view player_explorer_last5
with (security_invoker = on) as
with anchor as (
  select max(season) as season from fixtures where finished = true
),
identity as (
  select a.id as player_id, a.web_name, a.team_id, a.position, a.price,
         null::numeric as ownership, null::numeric as form, null::text as status
  from players_season_archive a
  where a.season = (select season from anchor)
  union all
  select pm.id, pm.web_name, pm.team_id, pm.position, pm.price,
         pm.ownership, pm.form, pm.status
  from players_master pm
  where not exists (
    select 1 from players_season_archive x where x.season = (select season from anchor)
  )
),
tname as (
  select ta.id as team_id, ta.short_name
  from teams_season_archive ta
  where ta.season = (select season from anchor)
  union all
  select tm.id, tm.short_name
  from teams tm
  where not exists (
    select 1 from teams_season_archive x where x.season = (select season from anchor)
  )
),
ranked as (
  select ph.*,
         row_number() over (partition by ph.player_id order by ph.gw desc) as rn
  from player_history ph
  where ph.minutes > 0
    and ph.season = (select season from anchor)
),
agg as (
  select player_id,
         sum(minutes)            as minutes,
         sum(total_points)       as total_points,
         sum(goals)              as goals,
         sum(assists)            as assists,
         sum(goals + assists)    as goal_involvements,
         sum(clean_sheets)       as clean_sheets,
         sum(cbit)               as cbit,
         sum(bps)                as bps,
         sum(xg)                 as xg,
         sum(xa)                 as xa,
         sum(xgi)                as xgi,
         sum(xgc)                as xgc
  from ranked
  where rn <= 5
  group by player_id
)
select
  i.player_id,
  i.web_name,
  t.short_name                                                as team,
  i.position,
  i.price,
  i.status,
  i.ownership,
  a.minutes,
  a.total_points,
  case when a.minutes > 0
       then round(a.total_points::numeric * 90 / a.minutes, 2)
  end                                                         as points_per_90,
  case when i.price > 0
       then round(a.total_points::numeric / i.price, 2)
  end                                                         as points_per_million,
  a.goals,
  a.assists,
  a.goal_involvements,
  a.xg::numeric(6,2)                                          as xg,
  a.xa::numeric(6,2)                                          as xa,
  a.xgi::numeric(6,2)                                         as xgi,
  a.xgc::numeric(6,2)                                         as xgc,
  a.clean_sheets,
  a.cbit,
  a.bps,
  null::numeric                                               as ict_index,
  i.form
from agg a
join identity i on i.player_id = a.player_id
left join tname t on t.team_id = i.team_id;

-- ---------------------------------------------------------------------------
-- TEAM — SEASON. W/D/L/GF/GA/CS from finished fixtures; xG/xA/xGC recomputed
-- from player_history via the anchor season's player→team mapping (NOT the
-- team_history view, which itself joins the live players_master and so is
-- mis-keyed for a past season). Per-GW: sum xg/xa, max xgc — matching the
-- team_history convention (migration 0002) — then summed across GWs.
-- ---------------------------------------------------------------------------
create view team_explorer_season
with (security_invoker = on) as
with anchor as (
  select max(season) as season from fixtures where finished = true
),
tname as (
  select ta.id as team_id, ta.short_name, ta.name,
         null::int as strength_home, null::int as strength_away
  from teams_season_archive ta
  where ta.season = (select season from anchor)
  union all
  select tm.id, tm.short_name, tm.name,
         tm.strength_overall_home, tm.strength_overall_away
  from teams tm
  where not exists (
    select 1 from teams_season_archive x where x.season = (select season from anchor)
  )
),
pteam as (
  select a.id as player_id, a.team_id
  from players_season_archive a
  where a.season = (select season from anchor)
  union all
  select pm.id, pm.team_id
  from players_master pm
  where not exists (
    select 1 from players_season_archive x where x.season = (select season from anchor)
  )
),
results as (
  select f.home_team_id as team_id, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from anchor)
  union all
  select f.away_team_id as team_id, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from anchor)
),
team_results as (
  select team_id,
         count(*)                        as matches_played,
         count(*) filter (where gf > ga) as wins,
         count(*) filter (where gf = ga) as draws,
         count(*) filter (where gf < ga) as losses,
         sum(gf)                         as goals_for,
         sum(ga)                         as goals_against,
         count(*) filter (where ga = 0)  as clean_sheets
  from results
  group by team_id
),
team_gw as (
  select pt.team_id, ph.gw,
         sum(ph.xg)  as gw_xg,
         sum(ph.xa)  as gw_xa,
         max(ph.xgc) as gw_xgc
  from player_history ph
  join pteam pt on pt.player_id = ph.player_id
  where ph.season = (select season from anchor)
  group by pt.team_id, ph.gw
),
team_xg as (
  select team_id,
         sum(gw_xg)  as total_xg,
         sum(gw_xa)  as total_xa,
         sum(gw_xgc) as xgc
  from team_gw
  group by team_id
)
select
  tn.team_id,
  tn.short_name,
  tn.name,
  coalesce(tr.matches_played, 0)                      as matches_played,
  coalesce(tr.wins, 0)                                as wins,
  coalesce(tr.draws, 0)                               as draws,
  coalesce(tr.losses, 0)                              as losses,
  coalesce(tr.wins, 0) * 3 + coalesce(tr.draws, 0)    as points,
  coalesce(tr.goals_for, 0)                           as goals_for,
  coalesce(tr.goals_against, 0)                       as goals_against,
  coalesce(tr.goals_for, 0) - coalesce(tr.goals_against, 0) as goal_difference,
  coalesce(tr.clean_sheets, 0)                        as clean_sheets,
  tx.total_xg::numeric(6,2)                           as total_xg,
  tx.total_xa::numeric(6,2)                           as total_xa,
  tx.xgc::numeric(6,2)                                as xgc,
  tn.strength_home,
  tn.strength_away
from tname tn
left join team_results tr on tr.team_id = tn.team_id
left join team_xg tx on tx.team_id = tn.team_id;

-- ---------------------------------------------------------------------------
-- TEAM — LAST 5 finished fixtures per team (+ last-5 GWs of team xg/xa/xgc)
-- ---------------------------------------------------------------------------
create view team_explorer_last5
with (security_invoker = on) as
with anchor as (
  select max(season) as season from fixtures where finished = true
),
tname as (
  select ta.id as team_id, ta.short_name, ta.name,
         null::int as strength_home, null::int as strength_away
  from teams_season_archive ta
  where ta.season = (select season from anchor)
  union all
  select tm.id, tm.short_name, tm.name,
         tm.strength_overall_home, tm.strength_overall_away
  from teams tm
  where not exists (
    select 1 from teams_season_archive x where x.season = (select season from anchor)
  )
),
pteam as (
  select a.id as player_id, a.team_id
  from players_season_archive a
  where a.season = (select season from anchor)
  union all
  select pm.id, pm.team_id
  from players_master pm
  where not exists (
    select 1 from players_season_archive x where x.season = (select season from anchor)
  )
),
results as (
  select f.home_team_id as team_id, f.gw, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from anchor)
  union all
  select f.away_team_id as team_id, f.gw, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from anchor)
),
ranked as (
  select r.*, row_number() over (partition by team_id order by gw desc) as rn
  from results r
),
last5 as (
  select * from ranked where rn <= 5
),
team_results as (
  select team_id,
         count(*)                        as matches_played,
         count(*) filter (where gf > ga) as wins,
         count(*) filter (where gf = ga) as draws,
         count(*) filter (where gf < ga) as losses,
         sum(gf)                         as goals_for,
         sum(ga)                         as goals_against,
         count(*) filter (where ga = 0)  as clean_sheets
  from last5
  group by team_id
),
team_gw as (
  select pt.team_id, ph.gw,
         sum(ph.xg)  as gw_xg,
         sum(ph.xa)  as gw_xa,
         max(ph.xgc) as gw_xgc
  from player_history ph
  join pteam pt on pt.player_id = ph.player_id
  where ph.season = (select season from anchor)
  group by pt.team_id, ph.gw
),
team_gw_ranked as (
  select tg.*, row_number() over (partition by team_id order by gw desc) as rn
  from team_gw tg
),
team_xg as (
  select team_id,
         sum(gw_xg)  as total_xg,
         sum(gw_xa)  as total_xa,
         sum(gw_xgc) as xgc
  from team_gw_ranked
  where rn <= 5
  group by team_id
)
select
  tn.team_id,
  tn.short_name,
  tn.name,
  coalesce(tr.matches_played, 0)                      as matches_played,
  coalesce(tr.wins, 0)                                as wins,
  coalesce(tr.draws, 0)                               as draws,
  coalesce(tr.losses, 0)                              as losses,
  coalesce(tr.wins, 0) * 3 + coalesce(tr.draws, 0)    as points,
  coalesce(tr.goals_for, 0)                           as goals_for,
  coalesce(tr.goals_against, 0)                       as goals_against,
  coalesce(tr.goals_for, 0) - coalesce(tr.goals_against, 0) as goal_difference,
  coalesce(tr.clean_sheets, 0)                        as clean_sheets,
  tx.total_xg::numeric(6,2)                           as total_xg,
  tx.total_xa::numeric(6,2)                           as total_xa,
  tx.xgc::numeric(6,2)                                as xgc,
  tn.strength_home,
  tn.strength_away
from tname tn
left join team_results tr on tr.team_id = tn.team_id
left join team_xg tx on tx.team_id = tn.team_id;

-- Re-apply grants (drop+create resets them). anon stays revoked (0008).
grant select on player_explorer_season to authenticated;
grant select on player_explorer_last5  to authenticated;
grant select on team_explorer_season   to authenticated;
grant select on team_explorer_last5    to authenticated;
