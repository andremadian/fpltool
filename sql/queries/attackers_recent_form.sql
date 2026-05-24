-- ============================================
-- Attackers — recent form (last 5 played GWs)
-- ============================================
-- Ranks players by total xGI over their last 5 games where they
-- actually got on the pitch, tiebroken by FPL form. Use this to
-- find who's creating most in-game right now.
--
-- Requires: migrations 0001 (base schema), 0002 (xgc in player_history)
--
-- Tunable knobs:
--   - LIMIT — how many rows to show
--   - games_played >= 3 — minimum recent games played
--   - mins >= 180 — minimum total recent minutes (excludes cameos)
--   - rn <= 5 — window size (raise for longer-term form)
-- ============================================

with last_5 as (
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
  pm.ownership
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id
where pm.position in ('FWD', 'MID', 'DEF')
  and a.games_played >= 3
  and a.mins >= 180
order by a.xgi_sum desc, pm.form desc
limit 30;
