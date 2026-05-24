# SQL queries

Hand-curated queries for FPL research in Supabase SQL Editor. Paste any file's contents into the editor and run.

All queries default to `LIMIT 30` and a 5-GW window over the last *played* GWs (`minutes > 0`). Tweak the comments at the top of each file for the knobs that matter.

## Catalog

| Query | What it answers | Sort key |
|---|---|---|
| `attackers_recent_form.sql` | Who's creating most attacking output right now (xGI + recency)? | `xgi_last_5 desc` |
| `defenders_recent_form.sql` | Who's putting up defensive bonus points on tight defenses right now? | `cbit_per_game desc, xgc_per_game asc` |
| `attackers_projection.sql` | Best attacking matchups for upcoming fixtures (xGI × opp xGC × form) | `projection_score desc` |
| `defenders_projection.sql` | Best defensive matchups for upcoming fixtures (CBIT × own xGC × opp xG × form) | `projection_score desc` |

## How "form" is computed

The two `_projection` queries compute their own form metric inline:

```
form_recent = sum(total_points over last 5 played GWs) / games_played
```

This is intentionally **not** FPL's built-in `form` field — FPL's form rolls over ~30 calendar days and is sometimes deflated by cup games or breaks. `form_recent` is strictly time-aligned with everything else in the projection (last 5 played GWs).

Both fields are returned (`fpl_form` and `form_recent`) so you can compare and decide which signal you trust more in a given situation.

## Score formulas

**Attacker projection:**
```
score = (xGI / game) × (opp team xGC / game) × (form_recent / 5)
```

**Defender projection:**
```
            (CBIT / game) × (form_recent / 5)
score = ─────────────────────────────────────────────
        (own xGC/game + 0.5) × (opp team xG/game + 0.5)
```

`+ 0.5` smoothing prevents divide-by-zero and dampens extreme matchups.

## When projections return zero rows

The two `_projection` queries depend on `fixtures.finished = false` rows existing. Out of season (e.g. mid-June to late-July), all 380 fixtures are finished and the queries return empty. Once the new season's fixtures land in the FPL API, the cron picks them up and projections come back.

Until then, use `_recent_form` queries — those work year-round on the existing `player_history` data.
