-- ============================================
-- Defenders — recent form (last 5 played GWs)
-- ============================================
-- Ranks defenders / keepers / mids by per-game CBIT, tiebroken by
-- low recent xGC (own team not conceding) and form. Use this to
-- find clean-sheet candidates with bonus-point ceiling.
--
-- Requires: migrations 0001 (base schema), 0002 (xgc in player_history)
--
-- Tunable knobs:
--   - LIMIT
--   - games_played >= 3
--   - mins >= 180
--   - rn <= 5 — window size
--   - position filter — narrow to ('DEF') or ('GKP') etc.
-- ============================================

with last_5 as (
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
  pm.ownership
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id
where pm.position in ('DEF', 'GKP', 'MID')
  and a.games_played >= 3
  and a.mins >= 180
order by cbit_per_game desc, xgc_per_game asc, pm.form desc
limit 30;
