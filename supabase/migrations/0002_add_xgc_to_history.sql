-- ============================================
-- 0002 — Add per-GW expected_goals_conceded
-- ============================================
-- Adds xgc to player_history so we can query a defender/keeper's
-- recent defensive context per gameweek (not just season-cumulative
-- xgc from players_master). The team_history view is recreated to
-- include team-level xgc per GW.
--
-- Note on team_xgc aggregation: xgc in FPL is per-player and scales
-- with minutes played. Summing across all 11 starters massively
-- overcounts. The team's xgc for a match equals the xgc of any
-- player who played the full 90, which is well-approximated by
-- MAX(xgc) across the team's players for that GW.
-- ============================================

alter table player_history add column xgc numeric(5,2);

drop view team_history;

create view team_history as
select
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
group by pm.team_id, t.name, ph.gw;
