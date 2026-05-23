-- ============================================
-- FPL DATA TABLES (populated by Python script)
-- ============================================

create table teams (
  id int primary key,
  name text not null,
  short_name text not null,
  strength_overall_home int,
  strength_overall_away int
);

create table players_master (
  id int primary key,
  web_name text not null,
  team_id int references teams(id),
  position text not null,         -- GKP, DEF, MID, FWD
  price numeric(3,1) not null,
  total_points int default 0,
  ownership numeric(4,1) default 0,
  points_per_90 numeric(5,2),
  price_per_point numeric(5,2),
  cbit int default 0,
  xg numeric(5,2),
  xa numeric(5,2),
  xgi numeric(5,2),
  xgc numeric(5,2),
  ict_index numeric(6,2),
  form numeric(4,2),
  minutes int default 0,
  updated_at timestamptz default now()
);

create index on players_master (position);
create index on players_master (team_id);
create index on players_master (price);

create table player_history (
  player_id int references players_master(id),
  gw int not null,
  minutes int default 0,
  total_points int default 0,
  goals int default 0,
  assists int default 0,
  clean_sheets int default 0,
  xg numeric(5,2),
  xa numeric(5,2),
  xgi numeric(5,2),
  bps int default 0,
  cbit int default 0,
  price numeric(3,1),
  primary key (player_id, gw)
);

create index on player_history (gw);

create view team_history as
select
  pm.team_id,
  t.name as team_name,
  ph.gw,
  sum(ph.goals) as total_goals,
  sum(ph.xg) as total_xg,
  sum(ph.xa) as total_xa,
  sum(ph.clean_sheets) as cs_count
from player_history ph
join players_master pm on pm.id = ph.player_id
join teams t on t.id = pm.team_id
group by pm.team_id, t.name, ph.gw;

-- ============================================
-- USER & CONVERSATION TABLES (populated in Phase 3+, empty for now)
-- ============================================

create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  fpl_team_id int,
  display_name text,
  created_at timestamptz default now()
);

create table user_rivals (
  user_id uuid references users(id) on delete cascade,
  league_id int not null,
  rival_fpl_team_id int not null,
  rival_name text,
  rival_squad jsonb,
  refreshed_at timestamptz default now(),
  primary key (user_id, league_id, rival_fpl_team_id)
);

create table conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references users(id) on delete cascade,
  title text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid references conversations(id) on delete cascade,
  role text not null,
  content text not null,
  tool_calls jsonb,
  created_at timestamptz default now()
);

create index on messages (conversation_id, created_at);

create table user_profile (
  user_id uuid primary key references users(id) on delete cascade,
  summary text,
  updated_at timestamptz default now()
);

alter table users enable row level security;
alter table user_rivals enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;
alter table user_profile enable row level security;

create policy "users see own row" on users for all using (auth.uid() = id);
create policy "users see own rivals" on user_rivals for all using (auth.uid() = user_id);
create policy "users see own conversations" on conversations for all using (auth.uid() = user_id);
create policy "users see own messages" on messages for all using (
  conversation_id in (select id from conversations where user_id = auth.uid())
);
create policy "users see own profile" on user_profile for all using (auth.uid() = user_id);
