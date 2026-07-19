-- Migration 0008 — PWA foundation (Phase 3B)
-- Read FPL_Sniper_Phase3B_PWA_Brief.md's loophole table for rationale.
--
-- BEFORE RUNNING:
--   1. Supabase Dashboard → Authentication → Users → Invite user
--      (andremadian@gmail.com) — done; UUID 8c4afa9c-e4ed-4b45-9f9e-02f347944ecb
--      is already substituted below.
--   2. (n/a — UUID already filled in.)
--   3. Disable public sign-ups + anonymous sign-ins in Authentication →
--      Sign In / Up (loophole #2) — not SQL, done in the dashboard.

-- 1) GAMEWEEKS — deadline source for the This-week countdown (loophole #4).
create table if not exists gameweeks (
  season text not null,
  gw int not null,
  deadline_time timestamptz not null,
  finished boolean default false,
  is_current boolean default false,
  is_next boolean default false,
  primary key (season, gw)
);

-- 2) MY STANDINGS ROW (loophole #16) — pairs with the fpl_user_engine.py change.
alter table league_rivals add column if not exists is_me boolean default false;

-- 3) PLAYER SEASON STATS — actual G+A etc. per player, CURRENT SEASON ONLY
--    (loopholes #6 + #17; anchors like every curated query, decision #10).
create or replace view player_season_stats
with (security_invoker = on) as
select
  h.season, h.player_id,
  pm.web_name, pm.team_id, pm.position, pm.price, pm.ownership,
  pm.xg, pm.xa, pm.xgi, pm.xgc, pm.form, pm.status,
  pm.chance_of_playing_next_round,
  sum(h.goals)        as goals,
  sum(h.assists)      as assists,
  sum(h.goals + h.assists) as goal_involvements,
  sum(h.minutes)      as minutes,
  sum(h.total_points) as total_points,
  sum(h.bps)          as bps,
  sum(h.cbit)         as cbit
from player_history h
join players_master pm on pm.id = h.player_id
where h.season = (select max(season) from player_history)
group by h.season, h.player_id, pm.web_name, pm.team_id, pm.position,
         pm.price, pm.ownership, pm.xg, pm.xa, pm.xgi, pm.xgc, pm.form,
         pm.status, pm.chance_of_playing_next_round;

-- 4) CURATED QUERIES AS VIEWS (loophole #5). One view per sql/queries/*.sql
--    file, same name. Transformations applied (loopholes #14 + #16):
--      * trailing `ORDER BY ... LIMIT 30` stripped — the client orders/limits;
--        the .sql files keep theirs for Studio use.
--      * none of the eight queries reference league_rivals directly (they read
--        rival_team_snapshots, already is_me-filtered at ingest via
--        load_unique_rival_ids) — audited, no `and not is_me` needed anywhere.
--    They self-anchor on the latest season/GW already (decisions #8/#10).

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
  )                                                           as projection_score
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
  pm.ownership
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
  )                                                           as projection_score
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
  pm.ownership
from agg a
join players_master pm on pm.id = a.player_id
join teams t on t.id = pm.team_id
where pm.position in ('DEF', 'GKP', 'MID')
  and a.games_played >= 3
  and a.mins >= 180;

create or replace view league_template_vs_global
with (security_invoker = on) as
with latest_gw as (
  select season, gw
  from rival_team_snapshots
  order by season desc, gw desc
  limit 1
),
rival_ownership as (
  select unnest(rts.player_ids) as player_id, count(*) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
  group by 1
),
total_rivals as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
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
  and pm.ownership < 30;

create or replace view my_squad_vs_rivals
with (security_invoker = on) as
with latest_gw as (
  select season, gw
  from rival_team_snapshots
  order by season desc, gw desc
  limit 1
),
my_squad as (
  select distinct unnest(uts.player_ids) as player_id
  from user_team_snapshots uts
  join latest_gw lg on lg.season = uts.season and lg.gw = uts.gw
),
rival_ownership as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
),
total_rivals as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
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
group by pm.web_name, t.short_name, pm.position, pm.price, pm.total_points, pm.form, tr.n;

create or replace view rival_captain_consensus
with (security_invoker = on) as
with latest_gw as (
  select season, gw
  from rival_team_snapshots
  order by season desc, gw desc
  limit 1
),
captains as (
  select rts.captain_id, count(*) as n_rivals_captaining
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
  where rts.captain_id is not null
  group by rts.captain_id
),
rival_total as (
  select count(distinct rival_fpl_team_id) as n
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
)
select
  lg.season,
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
left join player_history ph
  on ph.player_id = c.captain_id and ph.gw = lg.gw and ph.season = lg.season;

create or replace view rival_transfers_in_out
with (security_invoker = on) as
with latest_gw as (
  select season, gw
  from rival_team_snapshots
  order by season desc, gw desc
  limit 1
),
prev_gw as (
  select season, max(gw) as gw
  from rival_team_snapshots
  where season = (select season from latest_gw)
    and gw < (select gw from latest_gw)
  group by season
),
now_squads as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
),
prev_squads as (
  select rts.rival_fpl_team_id, unnest(rts.player_ids) as player_id
  from rival_team_snapshots rts
  join prev_gw pg on pg.season = rts.season and pg.gw = rts.gw
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
  join latest_gw lg on lg.season = rts.season and lg.gw = rts.gw
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
left join now_ownership no_ on no_.player_id = ap.player_id;

alter view team_history set (security_invoker = on);   -- loophole #3

-- 5) LOCKDOWN (loopholes #1 + #2 + #18 + #19). Idempotent; service role is
--    unaffected (BYPASSRLS) so the engines keep working unchanged.
--    Owner UUID (andremadian@gmail.com): 8c4afa9c-e4ed-4b45-9f9e-02f347944ecb
revoke all on all tables in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke all on all functions in schema public from anon;
revoke insert, update, delete, truncate, references, trigger
  on all tables in schema public from authenticated;
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public
  revoke insert, update, delete, truncate, references, trigger
  on tables from authenticated;

do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public'
  loop
    execute format('alter table public.%I enable row level security', t);
    begin
      execute format(
        'create policy "owner read" on public.%I for select to authenticated
         using ((select auth.uid()) = ''8c4afa9c-e4ed-4b45-9f9e-02f347944ecb''::uuid)', t);
    exception when duplicate_object then null;   -- re-runnable
    end;
  end loop;
end $$;
-- (select auth.uid()) — scalar subselect evaluates once per query, not per row
-- (loophole #18). The 0001 user-table policies remain; policies OR together.
--
-- CONVENTION FROM HERE ON (loophole #19): every migration after 0008 that adds
-- a new public table must enable RLS + add the "owner read" policy above; every
-- new view must be created with (security_invoker = on).
