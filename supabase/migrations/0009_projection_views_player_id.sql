-- Migration 0009 — add player_id to projection/form views (Phase 3B session 2)
-- attackers_projection / attackers_recent_form / defenders_projection /
-- defenders_recent_form (migration 0008) select pm.web_name but not pm.id,
-- leaving no reliable join key back to players_master/player_daily/
-- player_season_stats — needed by the PWA to filter a projection row to
-- my squad and to pull that player's price/ownership sparkline + season
-- stats on tap. Recreates all four with `pm.id as player_id` appended as
-- the LAST column of each select list.
--
-- Why appended, not prepended: `create or replace view` can only ADD
-- columns at the end — it cannot reorder or rename existing ones (Postgres
-- error 42P16). Appending also preserves each view's existing grants, which
-- a drop+recreate would reset. Column order is irrelevant to the PWA (it
-- selects by name). No GROUP BY impact — the outer select in each view is a
-- plain join, not an aggregate. Idempotent (create or replace).
--
-- Convention from loophole #19 (CLAUDE.md): every view keeps
-- security_invoker = on.

create or replace view attackers_projection
with (security_invoker = on) as
with current_season as (
  select max(season) as season from fixtures
),
last_5_per_player as (
  select ph.*,
         row_number() over (partition by player_id order by gw desc) as rn
  from player_history ph
  where minutes > 0
    and season = (select season from current_season)
),
player_recent as (
  select player_id,
         count(*)          filter (where rn <= 5) as recent_games,
         sum(minutes)      filter (where rn <= 5) as recent_mins,
         sum(xgi)          filter (where rn <= 5) as xgi_sum,
         sum(total_points) filter (where rn <= 5) as pts_sum,
         count(*)          filter (where rn <= 3) as games_3gw,
         sum(total_points) filter (where rn <= 3) as pts_sum_3gw
  from last_5_per_player
  where rn <= 5
  group by player_id
),
last_5_per_team as (
  select th.*,
         row_number() over (partition by team_id order by gw desc) as rn
  from team_history th
  where th.season = (select season from current_season)
),
team_def as (
  select team_id, avg(team_xgc) as avg_xgc_last_5
  from last_5_per_team
  where rn <= 5
  group by team_id
),
upcoming as (
  select id, gw, kickoff_time, home_team_id, away_team_id,
         home_difficulty, away_difficulty
  from fixtures
  where finished = false and gw is not null
    and season = (select season from current_season)
),
player_fixtures as (
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'H' as venue,
         u.away_team_id as opponent_team_id, u.home_difficulty as fdr
  from upcoming u
  join players_master pm on pm.team_id = u.home_team_id
  union all
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'A' as venue,
         u.home_team_id as opponent_team_id, u.away_difficulty as fdr
  from upcoming u
  join players_master pm on pm.team_id = u.away_team_id
)
select
  pm.web_name,
  pm.position,
  pm.price,
  pm.form                                                     as fpl_form,
  round((pr.pts_sum::numeric / pr.recent_games), 2)           as form_recent,
  case when pr.games_3gw > 0
       then round((pr.pts_sum_3gw::numeric / pr.games_3gw), 2)
  end                                                         as form_3gw,
  case when pr.games_3gw > 0
       then round(
              (pr.pts_sum_3gw::numeric / pr.games_3gw)
              - (pr.pts_sum::numeric / pr.recent_games),
              2
            )
  end                                                         as form_delta,
  pf.gw                                                       as upcoming_gw,
  pf.kickoff_time,
  pf.venue,
  pt.short_name                                               as player_team,
  ot.short_name                                               as opponent,
  pf.fdr,
  round((pr.xgi_sum / pr.recent_games)::numeric, 2)           as xgi_per_game,
  round(td.avg_xgc_last_5::numeric, 2)                        as opp_xgc_per_game,
  round(
    (
      pr.xgi_sum / pr.recent_games
      * td.avg_xgc_last_5
      * (pr.pts_sum::numeric / pr.recent_games / 5.0)
    )::numeric,
    3
  )                                                           as projection_score,
  pm.id                                                       as player_id
from player_fixtures pf
join players_master pm on pm.id = pf.player_id
join teams pt on pt.id = pf.player_team_id
join teams ot on ot.id = pf.opponent_team_id
join player_recent pr on pr.player_id = pm.id
join team_def td on td.team_id = pf.opponent_team_id
where pr.recent_games >= 3
  and pr.recent_mins >= 180
  and pm.position in ('MID', 'FWD', 'DEF');

create or replace view attackers_recent_form
with (security_invoker = on) as
with current_season as (
  select max(season) as season from fixtures
),
last_5 as (
  select
    ph.player_id,
    ph.gw,
    ph.minutes,
    ph.total_points,
    ph.xgi,
    ph.xg,
    ph.xa,
    ph.goals,
    ph.assists,
    row_number() over (partition by ph.player_id order by ph.gw desc) as recency_rank
  from player_history ph
  where ph.minutes > 0
    and ph.season = (select season from current_season)
),
agg as (
  select
    player_id,
    count(*)          as games_played,
    sum(minutes)      as mins,
    sum(total_points) as pts,
    sum(xgi)          as xgi_sum,
    sum(xg)           as xg_sum,
    sum(xa)           as xa_sum,
    sum(goals)        as goals,
    sum(assists)      as assists
  from last_5
  where recency_rank <= 5
  group by player_id
)
select
  pm.web_name,
  t.short_name                  as team,
  pm.position,
  pm.price,
  pm.form                       as fpl_form,
  a.games_played                as gp,
  a.xgi_sum::numeric(5,2)       as xgi_last_5,
  a.xg_sum::numeric(5,2)        as xg_last_5,
  a.xa_sum::numeric(5,2)        as xa_last_5,
  a.goals                       as goals_last_5,
  a.assists                     as assists_last_5,
  a.pts                         as pts_last_5,
  round(a.pts::numeric / a.games_played, 2) as avg_pts_per_game,
  pm.ownership,
  pm.id                         as player_id
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id
where pm.position in ('FWD', 'MID', 'DEF')
  and a.games_played >= 3
  and a.mins >= 180;

create or replace view defenders_projection
with (security_invoker = on) as
with current_season as (
  select max(season) as season from fixtures
),
last_5_per_player as (
  select ph.*,
         row_number() over (partition by player_id order by gw desc) as rn
  from player_history ph
  where minutes > 0
    and season = (select season from current_season)
),
player_recent as (
  select player_id,
         count(*)          filter (where rn <= 5) as recent_games,
         sum(minutes)      filter (where rn <= 5) as recent_mins,
         sum(cbit)         filter (where rn <= 5) as cbit_sum,
         sum(xgc)          filter (where rn <= 5) as xgc_sum,
         sum(clean_sheets) filter (where rn <= 5) as cs_sum,
         sum(total_points) filter (where rn <= 5) as pts_sum,
         count(*)          filter (where rn <= 3) as games_3gw,
         sum(total_points) filter (where rn <= 3) as pts_sum_3gw
  from last_5_per_player
  where rn <= 5
  group by player_id
),
last_5_per_team as (
  select th.*,
         row_number() over (partition by team_id order by gw desc) as rn
  from team_history th
  where th.season = (select season from current_season)
),
team_atk as (
  select team_id, avg(total_xg) as avg_xg_last_5
  from last_5_per_team
  where rn <= 5
  group by team_id
),
upcoming as (
  select id, gw, kickoff_time, home_team_id, away_team_id,
         home_difficulty, away_difficulty
  from fixtures
  where finished = false and gw is not null
    and season = (select season from current_season)
),
player_fixtures as (
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'H' as venue,
         u.away_team_id as opponent_team_id, u.home_difficulty as fdr
  from upcoming u
  join players_master pm on pm.team_id = u.home_team_id
  union all
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'A' as venue,
         u.home_team_id as opponent_team_id, u.away_difficulty as fdr
  from upcoming u
  join players_master pm on pm.team_id = u.away_team_id
)
select
  pm.web_name,
  pm.position,
  pm.price,
  pm.form                                                     as fpl_form,
  round((pr.pts_sum::numeric / pr.recent_games), 2)           as form_recent,
  case when pr.games_3gw > 0
       then round((pr.pts_sum_3gw::numeric / pr.games_3gw), 2)
  end                                                         as form_3gw,
  case when pr.games_3gw > 0
       then round(
              (pr.pts_sum_3gw::numeric / pr.games_3gw)
              - (pr.pts_sum::numeric / pr.recent_games),
              2
            )
  end                                                         as form_delta,
  pf.gw                                                       as upcoming_gw,
  pf.kickoff_time,
  pf.venue,
  pt.short_name                                               as player_team,
  ot.short_name                                               as opponent,
  pf.fdr,
  round((pr.cbit_sum::numeric / pr.recent_games), 1)          as cbit_per_game,
  round((pr.xgc_sum::numeric / pr.recent_games), 2)           as own_xgc_per_game,
  round(ta.avg_xg_last_5::numeric, 2)                         as opp_xg_per_game,
  round(
    (
      (pr.cbit_sum::numeric / pr.recent_games)
      * (pr.pts_sum::numeric / pr.recent_games / 5.0)
      / ((pr.xgc_sum::numeric / pr.recent_games + 0.5) * (ta.avg_xg_last_5 + 0.5))
    )::numeric,
    3
  )                                                           as projection_score,
  pm.id                                                       as player_id
from player_fixtures pf
join players_master pm on pm.id = pf.player_id
join teams pt on pt.id = pf.player_team_id
join teams ot on ot.id = pf.opponent_team_id
join player_recent pr on pr.player_id = pm.id
join team_atk ta on ta.team_id = pf.opponent_team_id
where pr.recent_games >= 3
  and pr.recent_mins >= 180
  and pm.position in ('DEF', 'GKP', 'MID');

create or replace view defenders_recent_form
with (security_invoker = on) as
with current_season as (
  select max(season) as season from fixtures
),
last_5 as (
  select
    ph.player_id,
    ph.gw,
    ph.minutes,
    ph.total_points,
    ph.cbit,
    ph.xgc,
    ph.clean_sheets,
    row_number() over (partition by ph.player_id order by ph.gw desc) as recency_rank
  from player_history ph
  where ph.minutes > 0
    and ph.season = (select season from current_season)
),
agg as (
  select
    player_id,
    count(*)          as games_played,
    sum(minutes)      as mins,
    sum(total_points) as pts,
    sum(cbit)         as cbit_sum,
    sum(xgc)          as xgc_sum,
    sum(clean_sheets) as cs_count
  from last_5
  where recency_rank <= 5
  group by player_id
)
select
  pm.web_name,
  t.short_name                  as team,
  pm.position,
  pm.price,
  pm.form                       as fpl_form,
  a.games_played                as gp,
  a.cbit_sum                    as cbit_last_5,
  round(a.cbit_sum::numeric / a.games_played, 1) as cbit_per_game,
  a.xgc_sum::numeric(5,2)       as xgc_last_5,
  round(a.xgc_sum::numeric / a.games_played, 2)  as xgc_per_game,
  a.cs_count                    as cs_last_5,
  a.pts                         as pts_last_5,
  round(a.pts::numeric / a.games_played, 2)      as avg_pts_per_game,
  pm.ownership,
  pm.id                         as player_id
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id
where pm.position in ('DEF', 'GKP', 'MID')
  and a.games_played >= 3
  and a.mins >= 180;
