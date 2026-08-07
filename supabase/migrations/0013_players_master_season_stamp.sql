-- Migration 0013 — stamp players_master with the season each row was last seen in
--
-- THE PROBLEM. players_master is upserted by `id` and never deleted, but FPL
-- re-issues player IDs every season (CLAUDE.md decision #10). At the
-- 2025/26 -> 2026/27 rollover the table held 841 rows while the new season
-- had only 570 registered players: 271 rows were 2025/26 leftovers still
-- carrying last season's price, total_points and team_id (id 624 "Bowen"
-- 187 pts, id 694 "Mukiele" 151, id 691 "Calvert-Lewin" 142, ...).
--
-- So "the current snapshot" silently included a quarter of last season. The
-- table could not answer "who is actually playing this season?" at all.
--
-- WHY NOT JUST DELETE THE LEFTOVERS. player_history.player_id carries a
-- foreign key onto players_master(id), and those leftover IDs each have a
-- full season of history rows behind them (id 624 has 38). Deleting them is
-- either blocked by the FK or, if forced with a cascade, destroys 2025/26
-- history. The identity archives already cover historical joins
-- (players_season_archive holds all 841 rows for 2025/26), but the FK makes
-- deletion the wrong tool regardless. So: mark, don't delete — which also
-- matches how decision #10 handles the rollover everywhere else.
--
-- WHAT THIS CHANGES. Adds players_master.last_seen_season, backfills it, and
-- teaches the two *_projection views to ignore rows from a past season.
-- fpl_engine.py stamps the column on every snapshot upsert from now on; its
-- startup schema assert requires this migration.
--
-- SCOPE NOTE — which views actually needed the filter. Only the two
-- *_projection views enumerate players by club
-- (`join players_master pm on pm.team_id = u.home_team_id`), which is the
-- one join that lets a stale row in on a re-issued team ID. Their final
-- select then inner-joins `player_recent`, built from current-season
-- player_history, so a stale row was already dropped before reaching the
-- output — the practical damage was an inflated intermediate join, not a
-- wrong row. The filter is applied where the leak starts so the views stop
-- depending on that downstream accident. The two *_recent_form views join
-- `pm.id = a.player_id` against current-season history aggregates and were
-- never exposed; they are deliberately left alone so that a season boundary
-- where the engine has not yet re-stamped rows degrades to stale-but-present
-- rather than empty.
--
-- Idempotent: `add column if not exists` + `create or replace view`. Replace
-- (not drop) preserves the existing grants, same reasoning as migration 0009.
-- Convention from loophole #19 (CLAUDE.md): every view keeps
-- security_invoker = on.

alter table players_master
  add column if not exists last_seen_season text;

comment on column players_master.last_seen_season is
  'Season whose bootstrap payload last refreshed this row (e.g. 2026/27). '
  'Rows from an earlier season are re-issued IDs kept only to satisfy the '
  'player_history FK — filter to the current season for "who plays now".';

-- Backfill 1: anyone in the most recent player_daily batch was refreshed by
-- the latest engine run, so that run's season is their last-seen season.
update players_master pm
set last_seen_season = pd.season
from (
  select distinct player_id, season
  from player_daily
  where as_of_date = (select max(as_of_date) from player_daily)
) pd
where pm.id = pd.player_id
  and pm.last_seen_season is distinct from pd.season;

-- Backfill 2: everything still unstamped predates that run. The identity
-- archive records which season each ID last belonged to.
update players_master pm
set last_seen_season = (
  select max(psa.season)
  from players_season_archive psa
  where psa.id = pm.id
)
where pm.last_seen_season is null;

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
-- Only current-season players may be enumerated by club: team IDs 1-20 are
-- re-issued each season, so a leftover row would otherwise attach itself to
-- whichever club inherited its old team_id.
player_fixtures as (
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'H' as venue,
         u.away_team_id as opponent_team_id, u.home_difficulty as fdr
  from upcoming u
  join players_master pm
    on pm.team_id = u.home_team_id
   and pm.last_seen_season = (select season from current_season)
  union all
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'A' as venue,
         u.home_team_id as opponent_team_id, u.away_difficulty as fdr
  from upcoming u
  join players_master pm
    on pm.team_id = u.away_team_id
   and pm.last_seen_season = (select season from current_season)
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
-- Same guard as attackers_projection: club enumeration must not pick up a
-- previous season's row on a re-issued team ID.
player_fixtures as (
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'H' as venue,
         u.away_team_id as opponent_team_id, u.home_difficulty as fdr
  from upcoming u
  join players_master pm
    on pm.team_id = u.home_team_id
   and pm.last_seen_season = (select season from current_season)
  union all
  select pm.id as player_id, pm.team_id as player_team_id,
         u.gw, u.kickoff_time, 'A' as venue,
         u.home_team_id as opponent_team_id, u.away_difficulty as fdr
  from upcoming u
  join players_master pm
    on pm.team_id = u.away_team_id
   and pm.last_seen_season = (select season from current_season)
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
