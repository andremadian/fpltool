-- ============================================
-- Rival transfers in / out — who's moving in the market
-- ============================================
-- For the most recent GW with rival data, shows which players had
-- the most rivals transferring them in or out, by diffing each
-- rival's current squad against their previous-GW squad.
--
-- Requires: migration 0004 (Phase 2 schema), at least TWO GWs of
-- rival_team_snapshots data. The first Phase 2 run only has one GW,
-- so this query returns empty until the second weekly capture.
--
-- Method:
--   transferred IN  = players in this-GW squad but not last-GW squad
--   transferred OUT = players in last-GW squad but not this-GW squad
--
-- Only rivals with snapshots in BOTH gameweeks are diffed — a rival
-- missing one snapshot is skipped, not treated as a full transfer.
-- ============================================

with latest_gw as (
  select max(gw) as gw from rival_team_snapshots
),
prev_gw as (
  select max(gw) as gw
  from rival_team_snapshots
  where gw < (select gw from latest_gw)
),
now_squads as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
),
prev_squads as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join prev_gw pg on pg.gw = rts.gw
),
rivals_with_both as (
  select distinct n.rival_fpl_team_id
  from now_squads n
  where exists (
    select 1 from prev_squads p where p.rival_fpl_team_id = n.rival_fpl_team_id
  )
),
transferred_in as (
  select n.player_id, count(*) as transfers_in_count
  from now_squads n
  join rivals_with_both rwb on rwb.rival_fpl_team_id = n.rival_fpl_team_id
  left join prev_squads p
    on p.rival_fpl_team_id = n.rival_fpl_team_id
   and p.player_id = n.player_id
  where p.player_id is null
  group by n.player_id
),
transferred_out as (
  select p.player_id, count(*) as transfers_out_count
  from prev_squads p
  join rivals_with_both rwb on rwb.rival_fpl_team_id = p.rival_fpl_team_id
  left join now_squads n
    on n.rival_fpl_team_id = p.rival_fpl_team_id
   and n.player_id = p.player_id
  where n.player_id is null
  group by p.player_id
),
now_ownership as (
  select player_id, count(*) as n_rivals_owning_now
  from now_squads
  group by player_id
),
total_rivals as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.gw = rts.gw
),
all_players as (
  select player_id from transferred_in
  union
  select player_id from transferred_out
)
select
  pm.web_name                                                                   as player_name,
  t.short_name                                                                  as team_short_name,
  coalesce(ti.transfers_in_count, 0)                                            as transfers_in_count,
  coalesce(to_.transfers_out_count, 0)                                          as transfers_out_count,
  coalesce(ti.transfers_in_count, 0) - coalesce(to_.transfers_out_count, 0)     as net_transfers,
  coalesce(no_.n_rivals_owning_now, 0)                                          as n_rivals_owning_now,
  round(100.0 * coalesce(no_.n_rivals_owning_now, 0)::numeric / nullif(tr.n, 0), 1) as pct_rival_ownership
from all_players ap
join players_master pm on pm.id = ap.player_id
join teams t on t.id = pm.team_id
cross join total_rivals tr
left join transferred_in ti on ti.player_id = ap.player_id
left join transferred_out to_ on to_.player_id = ap.player_id
left join now_ownership no_ on no_.player_id = ap.player_id
order by abs(coalesce(ti.transfers_in_count, 0) - coalesce(to_.transfers_out_count, 0)) desc,
         coalesce(ti.transfers_in_count, 0) desc;
