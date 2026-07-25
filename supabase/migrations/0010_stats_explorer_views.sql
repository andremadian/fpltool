-- Migration 0010 — Stats Explorer views (Phase 3C)
-- Four read-only curated views powering the PWA "Stats" tab: season and
-- last-5-GW windows for players and teams. Follows the loophole #19
-- convention (CLAUDE.md): security_invoker = on + explicit grant to
-- authenticated. No new tables, so no new RLS policy. All views self-anchor
-- on the current season (decision #10). The engines do not read these.

-- 1) PLAYER — SEASON TOTALS. Counting stats summed from player_history;
--    rate/expected stats read from players_master (the API's own season
--    figures), mirroring the existing player_season_stats view. Inner join
--    to history so the view is empty pre-GW1 (drives the "unlock after GW1"
--    empty state) and 0-minute players don't flood the table.
create or replace view player_explorer_season
with (security_invoker = on) as
with cs as (select max(season) as season from player_history),
agg as (
  select ph.player_id,
         sum(ph.minutes)            as minutes,
         sum(ph.total_points)       as total_points,
         sum(ph.goals)              as goals,
         sum(ph.assists)            as assists,
         sum(ph.goals + ph.assists) as goal_involvements,
         sum(ph.clean_sheets)       as clean_sheets,
         sum(ph.cbit)               as cbit,
         sum(ph.bps)                as bps
  from player_history ph
  where ph.season = (select season from cs)
  group by ph.player_id
)
select
  pm.id                                                       as player_id,
  pm.web_name,
  t.short_name                                                as team,
  pm.position,
  pm.price,
  pm.status,
  pm.ownership,
  a.minutes,
  a.total_points,
  pm.points_per_90,
  case when pm.price > 0
       then round(a.total_points::numeric / pm.price, 2)
  end                                                         as points_per_million,
  a.goals,
  a.assists,
  a.goal_involvements,
  pm.xg,
  pm.xa,
  pm.xgi,
  pm.xgc,
  a.clean_sheets,
  a.cbit,
  a.bps,
  pm.ict_index,
  pm.form
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id;

-- 2) PLAYER — LAST 5 GWs (minutes > 0), same recency logic as the projection
--    views. ict_index has no per-GW source, so it is null here.
create or replace view player_explorer_last5
with (security_invoker = on) as
with cs as (select max(season) as season from player_history),
ranked as (
  select ph.*,
         row_number() over (partition by ph.player_id order by ph.gw desc) as rn
  from player_history ph
  where ph.minutes > 0
    and ph.season = (select season from cs)
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
  pm.id                                                       as player_id,
  pm.web_name,
  t.short_name                                                as team,
  pm.position,
  pm.price,
  pm.status,
  pm.ownership,
  a.minutes,
  a.total_points,
  case when a.minutes > 0
       then round(a.total_points::numeric * 90 / a.minutes, 2)
  end                                                         as points_per_90,
  case when pm.price > 0
       then round(a.total_points::numeric / pm.price, 2)
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
  pm.form
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id;

-- 3) TEAM — SEASON. W/D/L, GF/GA/GD, clean sheets from finished fixtures
--    (home + away perspectives unioned); xG/xA/xGC from team_history. Left
--    join teams so all 20 clubs always show (a club with 0 finished matches
--    is still a valid row).
create or replace view team_explorer_season
with (security_invoker = on) as
with cs as (select max(season) as season from fixtures),
results as (
  select f.home_team_id as team_id, f.gw, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
  union all
  select f.away_team_id as team_id, f.gw, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
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
team_xg as (
  select team_id,
         sum(total_xg)  as total_xg,
         sum(total_xa)  as total_xa,
         sum(team_xgc)  as xgc
  from team_history
  where season = (select season from cs)
  group by team_id
)
select
  t.id                                                as team_id,
  t.short_name,
  t.name,
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
  t.strength_overall_home                             as strength_home,
  t.strength_overall_away                             as strength_away
from teams t
left join team_results tr on tr.team_id = t.id
left join team_xg tx on tx.team_id = t.id;

-- 4) TEAM — LAST 5 finished fixtures per team (+ last-5 GWs of team_history).
--    Exposes strength_home/away too (UI hides them in the last-5 window) so a
--    single TS interface covers both team views.
create or replace view team_explorer_last5
with (security_invoker = on) as
with cs as (select max(season) as season from fixtures),
results as (
  select f.home_team_id as team_id, f.gw, f.home_score as gf, f.away_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
  union all
  select f.away_team_id as team_id, f.gw, f.away_score as gf, f.home_score as ga
  from fixtures f
  where f.finished = true and f.season = (select season from cs)
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
th_ranked as (
  select th.*, row_number() over (partition by team_id order by gw desc) as rn
  from team_history th
  where th.season = (select season from cs)
),
team_xg as (
  select team_id,
         sum(total_xg)  as total_xg,
         sum(total_xa)  as total_xa,
         sum(team_xgc)  as xgc
  from th_ranked
  where rn <= 5
  group by team_id
)
select
  t.id                                                as team_id,
  t.short_name,
  t.name,
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
  t.strength_overall_home                             as strength_home,
  t.strength_overall_away                             as strength_away
from teams t
left join team_results tr on tr.team_id = t.id
left join team_xg tx on tx.team_id = t.id;

-- 5) GRANTS — authenticated reads (anon stays revoked from 0008).
grant select on player_explorer_season to authenticated;
grant select on player_explorer_last5  to authenticated;
grant select on team_explorer_season   to authenticated;
grant select on team_explorer_last5    to authenticated;
