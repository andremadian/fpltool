-- ============================================
-- My squad vs rivals — ownership comparison
-- ============================================
-- For the most recent GW with rival data, shows every player in my
-- squad alongside the percentage of my rivals (across all tracked
-- leagues) who also own them. Differentials surface at the top
-- (low rival ownership), template picks at the bottom.
--
-- Requires: migration 0004 (Phase 2 schema), plus user_team_snapshots
-- and rival_team_snapshots populated for the same GW.
--
-- Notes:
--   - "latest GW" comes from rival_team_snapshots — if rivals haven't
--     been captured yet for the current GW, falls back to the most
--     recent GW where rival picks exist.
--   - If you track multiple my_fpl_team_id values, the query unions
--     them via DISTINCT (so a player in both my squads counts once).
-- ============================================

with latest_gw as (
  select max(gw) as gw from rival_team_snapshots
),
my_squad as (
  select distinct unnest(uts.player_ids) as player_id
  from user_team_snapshots uts
  join latest_gw lg on lg.gw = uts.gw
),
rival_ownership as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
),
total_rivals as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
)
select
  pm.web_name                                                            as player_name,
  t.short_name                                                           as team_short_name,
  pm.position,
  pm.price,
  true                                                                   as i_own,
  count(ro.rival_fpl_team_id)                                            as rivals_owning_count,
  tr.n                                                                   as total_rivals,
  round(100.0 * count(ro.rival_fpl_team_id)::numeric / nullif(tr.n, 0), 1) as rival_ownership_pct,
  pm.total_points,
  pm.form
from my_squad ms
join players_master pm on pm.id = ms.player_id
join teams t on t.id = pm.team_id
cross join total_rivals tr
left join rival_ownership ro on ro.player_id = ms.player_id
group by pm.web_name, t.short_name, pm.position, pm.price, pm.total_points, pm.form, tr.n
order by rival_ownership_pct asc nulls last, pm.web_name;
