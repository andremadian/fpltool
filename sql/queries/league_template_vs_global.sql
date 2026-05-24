-- ============================================
-- League template vs global — mini-league hivemind picks
-- ============================================
-- Finds players who are heavily owned by my rivals but not globally
-- — i.e. the "mini-league template" that diverges from the wider
-- FPL hivemind. These are the players you'd want to cover if you
-- want to defend against rivals, or fade if you want to differentiate.
--
-- Requires: migration 0004 (Phase 2 schema), plus rival_team_snapshots
-- populated for the current GW, and players_master.ownership (Phase 1).
--
-- Tunable knobs:
--   - rival_ownership_pct >= 50 — how popular among rivals?
--   - global_ownership_pct < 30 — how rare globally?
--   Relax either threshold to see more rows.
-- ============================================

with latest_gw as (
  select max(gw) as gw from rival_team_snapshots
),
rival_ownership as (
  select unnest(rts.player_ids) as player_id, count(*) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
  group by 1
),
total_rivals as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
)
select
  pm.web_name                                                          as player_name,
  t.short_name                                                         as team_short_name,
  pm.position,
  pm.price,
  round(100.0 * ro.n::numeric / nullif(tr.n, 0), 1)                    as rival_ownership_pct,
  pm.ownership                                                         as global_ownership_pct,
  round(100.0 * ro.n::numeric / nullif(tr.n, 0) - pm.ownership, 1)     as template_delta,
  pm.form,
  pm.total_points
from rival_ownership ro
cross join total_rivals tr
join players_master pm on pm.id = ro.player_id
join teams t on t.id = pm.team_id
where 100.0 * ro.n::numeric / nullif(tr.n, 0) >= 50
  and pm.ownership < 30
order by template_delta desc;
