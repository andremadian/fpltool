-- Migration 0006 — player availability + transfer-momentum fields
-- (Phase 3A, item 1 — see docs/EXPANSION_PLAN.md)
--
-- The bootstrap-static payload the engine already downloads carries
-- injury/availability and transfer-momentum fields that were never stored.
-- This migration adds them to players_master; fpl_engine.py writes them
-- from this migration onward (weekly and daily runs).
--
-- Field notes:
--   status                        FPL availability code: a=available,
--                                 d=doubtful, i=injured, s=suspended,
--                                 u=unavailable/left league
--   news                          free-text injury/availability note
--                                 (e.g. "Knee injury - Expected back 21 Aug")
--   chance_of_playing_next_round  0/25/50/75/100, null when fully fit
--   transfers_in_event /
--   transfers_out_event           global transfers in/out during the
--                                 current gameweek — the price-change signal
--   cost_change_event             price change during the current GW, in £m
--                                 (API sends tenths; engine divides by 10,
--                                 same convention as players_master.price)
--
-- RLS stays off — global FPL data, consistent with decision #5 in CLAUDE.md.
-- Apply via Supabase SQL Editor. Idempotent (add column if not exists).

alter table players_master
  add column if not exists status text,
  add column if not exists news text,
  add column if not exists chance_of_playing_next_round int,
  add column if not exists transfers_in_event int default 0,
  add column if not exists transfers_out_event int default 0,
  add column if not exists cost_change_event numeric(3,1) default 0;

comment on column players_master.status is
  'FPL availability: a=available d=doubtful i=injured s=suspended u=unavailable';
comment on column players_master.chance_of_playing_next_round is
  '0/25/50/75/100; null = fully fit (FPL only sets this for flagged players)';
comment on column players_master.cost_change_event is
  'Price change during current GW in £m (API tenths / 10)';
