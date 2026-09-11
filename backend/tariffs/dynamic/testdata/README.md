# Dynamic tariff fixtures

Real responses, captured live on 2026-09-11, plus synthetic files for the shapes a
single real day does not contain.

## Captured

| File | Endpoint | What it is |
|---|---|---|
| `groupe_e_v2_day.json` | `https://api.tariffs.groupe-e.ch/v2/tariffs` | One day of the `vario` product: 96 quarter-hours carrying `grid` and `integrated`. Timestamps are local Swiss time with offset. **22 of the 96 `grid` values are negative** (min `-0.0543`) — that is the fixture's whole point, negative grid-usage prices are how a dynamic tariff steers consumption into the solar peak, and no synthetic file would be believed. |
| `bkw_energyreturn_day.json` | `https://api.bkw.ch/api/dyntariffs/v1/Tariffs/energyreturn` | One day of feed-in remuneration: 96 quarter-hours carrying `feed_in`, timestamps in UTC. |

**The BKW capture cannot be re-taken.** That endpoint accepts no query parameters and
serves only the current day out of a cache; the day it was captured is gone from the
operator. Do not regenerate it — re-capturing gives a different day, not this one.

The Groupe E capture is re-takeable for roughly nine months, after which the operator
drops it too.

## Synthetic

Built here rather than captured, because a single real day contains none of them:

| File | Shape |
|---|---|
| `vse_v1_multi_unit.json` | One component carrying `CHF_kWh` *and* `CHF_m` in the same interval — the reason the component is an array at all, and the case that makes reading `[0]` wrong |
| `vse_v1_gap.json` | A day with intervals missing in the middle, which BKW documents as normal behaviour |
| `vse_v1_dst_spring.json` | The spring-forward day: 92 intervals, not 96 — `01:45+01:00` is followed by `03:00+02:00` |
| `vse_v1_dst_autumn.json` | The fall-back day: 100 intervals, with `02:00`–`03:00` appearing twice under different offsets |
| `vse_v1_empty.json` | `{"publication_timestamp": "", "prices": []}` — what Groupe E answers with HTTP 200 for a range it has no data for |
| `vse_v2_grid.json` | A v2 (2027) payload, where the component is an object rather than an array — the parser must refuse it by name rather than misread it |
