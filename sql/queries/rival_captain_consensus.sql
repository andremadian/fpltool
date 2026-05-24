-- ============================================
-- Rival captain consensus — who's the popular captain
-- ============================================
-- For the most recent GW with rival data, shows the captaincy
-- distribution across rivals: which players were captained, how
-- many rivals captained them, and what those captaincies scored
-- (player_history.total_points × 2).
--
-- Requires: migration 0004 (Phase 2 schema), plus rival_team_snapshots
-- and player_history populated for the same GW.
--
-- Note on points doubling: brief specifies × 2. Triple-captain chip
-- weeks will under-report by one multiplier of the captain's points.
-- If you want chip-aware accounting, join chip_used and switch the
-- multiplier conditionally.
-- ============================================

with latest_gw as (
  select max(gw) as gw from rival_team_snapshots
),
captains as (
  select rts.captain_id, count(*) as n_rivals_captaining
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
  where rts.captain_id is not null
  group by rts.captain_id
),
rival_total as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
)
select
  lg.gw,
  pm.web_name                                                     as captain_player_name,
  t.short_name                                                    as captain_team,
  c.n_rivals_captaining,
  round(100.0 * c.n_rivals_captaining::numeric / nullif(rt.n, 0), 1) as pct_of_rivals_captaining,
  coalesce(ph.total_points, 0) * 2                                as captain_points_scored
from captains c
cross join latest_gw lg
cross join rival_total rt
join players_master pm on pm.id = c.captain_id
join teams t on t.id = pm.team_id
left join player_history ph on ph.player_id = c.captain_id and ph.gw = lg.gw
order by c.n_rivals_captaining desc, pm.web_name;
