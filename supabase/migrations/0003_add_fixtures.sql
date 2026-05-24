-- ============================================
-- 0003 — Fixtures table
-- ============================================
-- Stores every fixture in the current FPL season (past + future).
-- Used for matchup projections: "for each upcoming fixture this
-- player has, what's the opponent's recent defensive form?"
--
-- Notes:
-- * `gw` is the FPL `event` field. Can be null for unscheduled fixtures
--   (e.g. blank gameweeks awaiting reschedule).
-- * `home_difficulty` / `away_difficulty` are FPL's official Difficulty
--   Rating (1-5, 5 = hardest). Useful as a baseline matchup signal
--   that doesn't require recent xG data — works even in GW1.
-- * `home_score` / `away_score` are null until `finished = true`.
-- ============================================

create table fixtures (
  id int primary key,
  gw int,
  kickoff_time timestamptz,
  home_team_id int references teams(id),
  away_team_id int references teams(id),
  home_difficulty int,
  away_difficulty int,
  home_score int,
  away_score int,
  finished boolean default false
);

create index on fixtures (gw);
create index on fixtures (home_team_id);
create index on fixtures (away_team_id);
create index on fixtures (finished);
