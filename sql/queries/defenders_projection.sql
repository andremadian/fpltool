-- ============================================
-- Defenders — projection for upcoming fixtures
-- ============================================
-- For each defender's upcoming fixture, scores them by
--   (CBIT/game last 5)  ×  (form_recent / 5)
--     ───────────────────────────────────────────────────────
--   (own xGC/game last 5 + 0.5)  ×  (opp xG/game last 5 + 0.5)
--
-- High CBIT volume + tight own defense + opponent not creating
-- + currently in form = high score. The +0.5 prevents divide-by-zero
-- and dampens extreme matchups.
--
-- Requires: migrations 0001 (base), 0002 (xgc), 0003 (fixtures)
--
-- Tunable knobs:
--   - LIMIT
--   - rn <= 5 — window size
--   - games_played >= 3, mins >= 180
--   - position filter — narrow to 'DEF' for pure defender picks
--   - The +0.5 smoothing constants — raise to dampen, lower for harsher rejection of bad matchups
-- ============================================

with last_5_per_player as (
  select ph.*,
         row_number() over (partition by player_id order by gw desc) as rn
  from player_history ph
  where minutes > 0
),
player_recent as (
  select player_id,
         count(*)          as recent_games,
         sum(minutes)      as recent_mins,
         sum(cbit)         as cbit_sum,
         sum(xgc)          as xgc_sum,
         sum(clean_sheets) as cs_sum,
         sum(total_points) as pts_sum
  from last_5_per_player
  where rn <= 5
  group by player_id
),
last_5_per_team as (
  select th.*,
         row_number() over (partition by team_id order by gw desc) as rn
  from team_history th
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
  )                                                           as projection_score
from player_fixtures pf
join players_master pm on pm.id = pf.player_id
join teams pt on pt.id = pf.player_team_id
join teams ot on ot.id = pf.opponent_team_id
join player_recent pr on pr.player_id = pm.id
join team_atk ta on ta.team_id = pf.opponent_team_id
where pr.recent_games >= 3
  and pr.recent_mins >= 180
  and pm.position in ('DEF', 'GKP', 'MID')
order by projection_score desc, pf.gw asc
limit 30;
