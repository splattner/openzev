# ADR 0044: Live energy data is ephemeral, measured only, and shows a split only when it is exact

- Status: Proposed
- Date: 2026-10-30

## Context

[SPEC-2026-live-energy-data](../specs/2026-10-live-energy-data.md) ([#1032](https://github.com/splattner/openzev/issues/1032))
adds current power (W) per metering point, reported by a device the participant or manager already
runs, so participants can decide *now* whether to start a load. It builds on the energy data source of
[SPEC-2026-supplementary-energy-data](../specs/2026-10-supplementary-energy-data.md) and its rules
([ADR 0030](0030-supplementary-energy-data-is-not-billing-input.md), [ADR 0031](0031-integration-credentials-encrypted-under-a-dedicated-key.md),
[ADR 0033](0033-energy-data-flag-follows-the-integration-key.md)).

Live data differs from both the official readings and the 15-minute supplementary history:

- **Volume and lifetime.** A source pushes every ~10 seconds. The value is worth something for about
  a minute; nobody needs last Tuesday's 14:03:20 sample, and the official data covers the past.
- **Coverage is almost never complete.** In a typical ZEV the producer has a live device (inverter,
  Solar Manager) and few or no consumers do. A vZEV has no shared main meter.
- **The allocation needs both totals.** Under the shared allocation service
  ([ADR 0013](0013-shared-allocation-service.md)) every consumer's local share at an instant is the same
  fraction, `min(P, C) / C`. It needs the ZEV's production `P` *and* consumption `C`. With only some
  consumers reporting, `C` is known only from below, and the only valid statements are upper bounds
  ("at most 3 kW spare"). Those overstate exactly in the direction a participant acts on.
- **OpenZEV has no main meter.** A `MeteringPoint` is something whose readings are imported, assigned
  and billed. The grid operator's meter at the building's grid connection is none of those, yet in a
  physical ZEV its net power `N = C − P` is the cheapest way to know `C`: one reader instead of one
  per flat.
- **It is more personal than history.** A live household value shows whether someone is at home now.

## Decision

1. **Ephemeral storage.** Live values live in the cache (Valkey) only, behind `metering/live/store.py`:
   the latest sample per source with a TTL of `LIVE_MAX_AGE_S`, plus 5-minute mean buckets for a rolling
   `LIVE_CURVE_RETENTION_H` (48 h). They are never written to Postgres, never backed up or exported,
   and never summed into `SupplementaryReading` or any other history. A cache flush loses them, and that
   is acceptable.
2. **Measured only.** A sample older than `LIVE_MAX_AGE_S` (60 s) is missing, never "last known". A
   5-minute bucket is the mean of the samples that arrived in it; an empty bucket is a gap. Nothing is
   interpolated, extrapolated or estimated.
3. **Three tiers; the split only when exact.** A ZEV snapshot is classified:
   - `none`: no fresh live value at all.
   - `production`: every metering point that can produce has a fresh value, but `C` is not known
     exactly. The snapshot shows the ZEV's production now and the coverage, with the explicit note that
     other participants' current use is unknown. **No split, no surplus, no bound.**
   - `exact`: `P` is complete *and* `C` is known, either because every metering point that consumes
     has a fresh value, or (physical ZEV only) because the connection-point source is fresh, so
     `C = max(P + N, 0)`. Only then are the surplus, the local share and the per-participant split shown.
   If any producing point is missing, the tier is `none` for the ZEV totals: a partial production figure
   is not shown as "the ZEV's production".
4. **The split reuses billing's arithmetic.** The per-participant figures call
   `allocation.split.split_consumption` and `split_production` with watts in place of kWh. The live
   package imports from `allocation/`; never the reverse (the `SupplementaryIsolationTests` rule of
   ADR 0030 extends to `metering/live/`).
5. **The connection point is a live-only source on the ZEV**, not a metering point. A
   `SupplementarySource` with `target = connection_point` has no metering point, provides `live` only,
   exists at most once per ZEV, only for `zev_type = zev`, and is held by the ZEV (connected by a
   manager). Nothing that reads `MeteringPoint` or `MeterReading` sees it.
6. **Never billing input.** ADR 0030 applies unchanged: live values and forecasts reach no invoice,
   allocation result, data-quality check or statistics surface built on history.

## Consequences

Positive:
- The Postgres write load and backup size do not grow with the number of live devices.
- What a participant sees is either measured and exact, or plainly labelled as partial; it never
  promises spare energy the ZEV does not have.
- The live view and the later invoice share one formula.
- Adding the connection point changes no billing, import or data-quality code path.

Trade-offs:
- Without a connection-point reader (physical ZEV) or a live value from every consumer, participants see
  production only. In a vZEV, `exact` needs every consumer.
- A Valkey restart empties today's curve. Instances whose Valkey is not persistent lose it on every
  restart.
- A producer whose live device goes offline drops the whole ZEV to `none`; the coverage line names it to
  managers.
- `C = P + N` assumes every load behind the connection point is metered; unmetered common loads make
  `C` slightly larger than the sum the invoice will use. The value stays indicative.

## Alternatives considered

1. **Show upper bounds with partial coverage** ("at most y kW local").
   - Mathematically valid, but it overstates availability in the direction the participant acts on, and
     gives nothing at all when a producer is missing. Rejected in favour of "production now" plus an
     honest note.
2. **Persist live values in Postgres, or aggregate them into `SupplementaryReading`.**
   - Turning sampled power with gaps into 15-minute energy is an estimate, it would compete with the
     source's own history capability, and it multiplies storage. A "keep until the official data
     arrives" bridge is a possible follow-up.
3. **Model the main meter as a new `MeteringPointType`.**
   - Every reader of metering points (imports, totals, data quality, invoices, lists, exports) would have
     to exclude it, or its energy would be counted twice. A live-only source touches none of them.
4. **Server push (websockets/SSE) or native MQTT ingest.**
   - Polling every 10 to 30 s while the page is visible is enough for the decision this supports, and
     HTTP push covers Home Assistant and Shelly without operating a broker. Both stay future ideas.

## Notes

- Settings: `LIVE_MAX_AGE_S` (60), `LIVE_MIN_PUSH_INTERVAL_S` (5), `LIVE_CURVE_BUCKET_S` (300),
  `LIVE_CURVE_RETENTION_H` (48).
- The tier rules and their tests live in `metering/live/snapshot.py` and `metering/live/test_snapshot.py`.
