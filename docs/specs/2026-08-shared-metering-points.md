# Feature Spec: Shared metering points with cost-allocation weights

- Spec ID: SPEC-2026-08-shared-metering-points
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: spalinger
- Created: 2026-08-05
- Target Release: TBD
- Related Issues: [#387 Shared metering points: bill each participant their share of a common-area meter](https://github.com/splattner/openzev/issues/387)
- Related ADRs: [ADR 0013](../adr/0013-shared-allocation-service.md), [ADR 0002](../adr/0002-invoice-allocation-model.md)
- Impacted Areas: backend | frontend | docs

<!--
  Code references are by symbol name, not line number: this spec's predecessor
  draft used line anchors and four of them had drifted within 32 commits, while
  every symbol name survived. Verified against main (61a4aa8) on 2026-08-23.
-->

---

## 1. Problem and outcome

A common-area (*Allgemein*) metering point — shared connection, stairwell,
lift, laundry — is often legitimately held by one participant of record. Today
OpenZEV bills that meter entirely to its holder, who splits the amount by hand
outside the system: the split is invisible to the other participants, and the
system produces one invoice where it should produce one share per participant.

**Outcome:** mark an assignment as *community-allocated* and have every
participant's invoice already contain their share of that meter's energy,
per-kWh levies and per-metering-point fees. Shares are weighted by each
participant's **allocation weight** (`allocation_weight`): equal split is the
special case where all weights are equal, not a separate mode.

**Decision note.** Community-meter costs are allocated using a positive,
unitless participant `allocation_weight`. The system derives each participant's
allocation share by normalizing eligible participants' weights at the applicable
date (energy) or month (fees). `allocation_weight` is not a percentage,
per-mille value, or Swiss STWE Wertquote — the legal distinction is spelled out
at §5.2. This supersedes issue #387's recorded "Split key: equal per
participant" decision, per the issue's own invitation ("none is closed off").

**Two cost drivers, two split keys.** A shared *fee* (metering administration,
a service contract) and Allgemeinstrom (common-area consumption) are different
cost drivers, and Swiss practice splits them differently: administration per
account, common-area electricity by value share. Forcing both onto one key
would make setting a weight for the common meter silently re-split the shared
fees, which is not what anybody asked for.

So the key is chosen where the cost is defined:

| Cost | Split key | Chosen on |
|---|---|---|
| Community metering point (Allgemeinstrom) | Always by `allocation_weight` | — (that is the feature) |
| `SHARED_MONTHLY_FEE` / `SHARED_YEARLY_FEE` | `equal` (headcount) or `weight` | `Tariff.split_key`, default `equal` |

`Tariff.split_key` defaults to `equal`, which is exactly today's
`unit_price / count` behaviour — so every existing shared-fee tariff is
unaffected, and the 22 existing shared-fee tests pass unmodified. A ZEV that
wants weighted lift electricity *and* per-account metering administration can
express both. "Split key" is the issue's own vocabulary (#387's decision
table), reused here deliberately.

### 1.1 Terminology and invariants

| Term | Meaning |
|---|---|
| `allocation_mode` | Assignment field, `personal` \| `community` — whether a meter's costs go to the holder alone or are split across eligible participants |
| `allocation_weight` | Positive unitless participant input; the basis for splitting community costs |
| `allocation_share` | Derived weight share, computed on demand, never stored |
| `split_key` | Tariff field, `equal` \| `weight` — which denominator a `SHARED_*` fee uses. Does not apply to community metering points, which always use weight |
| `ownership_value_share` | Legal STWE ownership share (future, out of scope): a fraction with a common denominator under Art. 712e ZGB |

`allocation_mode` (who pays) and `split_key` (how a shared fee is divided) are
independent: the first is a property of an assignment, the second of a tariff.

Invariants:

- A community meter remains assigned to its holder of record (provenance, UI,
  data quality).
- The holder has no preferential billing treatment and participates in
  allocation under the same rules as every eligible participant.
- Shared costs are allocated only to eligible members, at the applicable date
  for energy and at the month for fees.
- `SHARED_MONTHLY_FEE` / `SHARED_YEARLY_FEE` are existing tariff billing
  modes — a different concept from `allocation_mode`; their names are
  unchanged for data/API compatibility.
- Community-meter allocation always uses `allocation_weight`. A `SHARED_*`
  fee uses whichever key its own tariff names, defaulting to `equal`, so
  setting a weight never changes a shared fee that did not opt in.
- All allocated monetary amounts conserve to the source amount within the
  documented rounding convention (§9).
- **Personal-vs-community is decided per timestamp, never per queryset** (§7.3).

## 2. Acceptance criteria

- [ ] An assignment can be marked `community` via UI and API; default is `personal`
- [ ] Every participant's invoice contains their weight-based share of a community meter's energy, levies and per-metering-point fees
- [ ] The holder pays their share like everyone else; a sole eligible participant carries the meter alone
- [ ] Regenerating one participant alone yields the same shares as a full run
- [ ] Shared energy follows membership at the reading's date; shared fees follow membership at the month
- [ ] A meter that is personal for part of a period and community for the rest is billed correctly in both windows, with no double billing and no lost readings (§7.3)
- [ ] Dashboards (analytics, pdf_stats), annual statement and hourly profiles reconcile with invoices for community meters
- [ ] A `SHARED_*` tariff with `split_key = equal` bills exactly as it does today, whatever weights are set; with `split_key = weight` it splits by weight
- [ ] Setting a participant's `allocation_weight` changes community-meter shares and no `equal`-keyed shared fee
- [ ] The 22 existing shared-fee tests pass **unmodified**; the 10 reconciliation tests keep their existing assertions with the fixture extended by a community meter
- [ ] New i18n keys exist in all four locales — `frontend/tests/locale-parity.test.ts` (added in #452) fails otherwise
- [ ] `python -m pytest -q`, `npm run test:unit`, `npm run build` green

## 3. Scope

### In scope

| Area | Details |
|---|---|
| `zev` models | `MeteringPointAssignment.allocation_mode` enum; `Participant.allocation_weight` field; migration |
| `zev` serializers | `allocation_mode` exposed via `fields = "__all__"`; `allocation_weight` added to `ParticipantSerializer` explicit field list |
| `tariffs` model | `Tariff.split_key` enum (`equal` \| `weight`, default `equal`); migration. `TariffSerializer` uses `fields = "__all__"`, so no serializer change |
| `allocation/windows.py` | Window tuples carry the allocation mode; new `assignment_at()` resolution object; `participant_at` / `participant_on` / `is_held_by` unchanged |
| `allocation/read_model.py` | `AllocatedReading` carries holder + allocation mode so consumers can distribute community readings instead of attributing them |
| `invoices/engine.py` | Per-timestamp allocation-mode gate in the personal loops, community querysets, date- and month-granular share helpers, price-once-allocate-second, per-metering-point fee changes, bucket plumbed into line items/descriptions, shared kWh in invoice totals |
| ADR 0013 consumers | `invoices/pdf_stats.py`, `invoices/pdf_charts.py`, `invoices/annual_statement.py`, `metering/analytics.py` distribute shares instead of attributing to the holder |
| `zev/transfer` | Export/import field whitelists (`schema.py`) carry `allocation_mode`, `allocation_weight` and `split_key` so sharing round-trips whole-ZEV export/import (#410) — §6 |
| Frontend | Mode selector + badge (metering points), weight field + computed-share indicator (participants), split-key selector + hint rewording (tariffs), 4 locales |
| Docs | Baseline spec updates: `2026-03-community-and-access.md`, `2026-03-metering-point-management.md`, `2026-03-tariffs-and-billing-engine.md` |

### Out of scope

- Weight history/versioning: editing a participant's weight applies to every
  period they appear in on regeneration (documented, not prevented).
- A per-*assignment* split key for community metering points: every community
  meter allocates by `allocation_weight`. Splitting one common meter equally
  while another follows the weight is a follow-up, and would go on the
  assignment next to `allocation_mode`. (Shared *fees* are configurable per
  tariff — see §5.3.)
- More than one weight per participant: a single `allocation_weight` is the
  only weight basis. A deployment wanting, say, floor area for heating and
  value share for the lift needs the general allocation-method framework
  below, not a second weight column.
- The legal property Wertquote (Art. 712e ZGB) and a general
  allocation-method framework (`CostAllocationRule` / per-cost-type keys such
  as area or measured consumption): documented follow-ups — §5.2.
- `feasibility` app: planning math keeps its hypothetical equal-split prices
  (it uses `allocation/split.py` scalars, not assignment windows).
- Contract PDF text and email flows (line items arrive as ordinary items).
- Billing modes other than the existing eight.

## 4. Actors, permissions, and ZEV scope

| Actor | Capability | Mechanism |
|---|---|---|
| ZEV owner / admin | Set `allocation_mode` on assignments, edit `allocation_weight` | Existing `MeteringPointAssignmentPermission` (assignments) and `BaseZevScopedPermission` (participants) on the existing viewsets — no new permission classes |
| Participant (self-service) | None — cannot edit own weight or mode | Same viewsets, unchanged scoping |

> `ParticipantViewSet` used `ParticipantManagementPermission` until #419 removed
> that empty subclass; it now uses `BaseZevScopedPermission` directly.

All endpoints stay ZEV-scoped via `ZevScopedQuerySetMixin` (`zev/scoping.py`)
and mutations stay audit-logged via `AuditedUpdateMixin` (`audit/mixins.py`),
both already mounted on `ParticipantViewSet` and
`MeteringPointAssignmentViewSet`. Since #425 that mixin also scopes **writes**,
so a payload naming another community's ZEV is rejected — the new fields
inherit that protection with no extra work. No new views.

## 5. Data model

### 5.1 `MeteringPointAssignment`

**Model:** `zev.models.MeteringPointAssignment`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `allocation_mode` | `CharField(max_length=10, choices=AllocationMode.choices)` | `AllocationMode.PERSONAL` | New. `AllocationMode(models.TextChoices)`: `PERSONAL = "personal"`; `COMMUNITY = "community"` |

Existing validation is unchanged: `clean()` enforces same-ZEV participant,
`valid_to >= valid_from`, participant-validity containment, and
`_validate_no_overlap()` — a metering point still has exactly one assignment at
any time, regardless of allocation mode. Since #390 that overlap check runs from
`save()` as well as `clean()`, so a programmatic write cannot create the
overlapping windows the allocation runtime refuses to resolve.

**A meter can be `PERSONAL` in one window and `COMMUNITY` in another**
(time-bounded sharing). This is the case §7.3 exists to get right.

**Serializer:** `MeteringPointAssignmentSerializer` — `fields = "__all__"`, so
`allocation_mode` is exposed and writable with no serializer change; its
`validate()` already runs `full_clean()`.

**Migration:** a single `AddField` per model with default `PERSONAL` /
`Decimal("1")`; existing rows get the defaults, no data migration, reversible.

### 5.2 `Participant`

**Model:** `zev.models.Participant`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `allocation_weight` | `DecimalField(max_digits=12, decimal_places=4)` | `Decimal("1")` | New. `MinValueValidator(Decimal("0.0001"))` at the field (surfaces in admin, forms and the API). Unitless relative weight — **not** a percentage, per-mille or property Wertquote. |

The legal distinction, once: under Art. 712e ZGB the Wertquote is an STWE
ownership share recorded as a fraction with a common denominator in the
Begründungsakt. In an owner-ZEV of houses, common costs are *often* split by
the property Wertquote, but the internal ZEV billing key is defined by the
ZEV's regulation or agreement — a legal ownership share is not automatically a
billing key. `allocation_weight` is a purely internal billing input, and the
two must not be conflated. `max_digits=12` is a pure storage cap
(99'999'999.9999), not a domain limit.

Validation is field-level: `allocation_weight <= 0` → validation error on
`allocation_weight` (a `clean()` rule would duplicate the validator; DRF
propagates model-field validators onto the serializer field automatically, so
the API returns 400 without serializer changes — `ParticipantSerializer.validate()`
is custom validation and does not run `full_clean()`). No sum-to-N constraint:
membership changes over time, and shares are normalized (§7.1), so any positive
weight set is valid. Rendered as a plain decimal weight ("1", "1.25", "200").

**Serializer:** `ParticipantSerializer` uses an explicit `fields` list — add
`"allocation_weight"` to `fields` (not to `read_only_fields`).

### 5.3 `Tariff`

**Model:** `tariffs.models.Tariff`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `split_key` | `CharField(max_length=10, choices=SplitKey.choices)` | `SplitKey.EQUAL` | New. `SplitKey(models.TextChoices)`: `EQUAL = "equal"`; `WEIGHT = "weight"`. Read **only** for `SHARED_MONTHLY_FEE` / `SHARED_YEARLY_FEE`; ignored by every other billing mode |

Defaulting to `EQUAL` is what keeps this change invisible to existing data: a
shared-fee tariff that has never heard of weights keeps dividing by headcount,
which is why the 22 existing shared-fee tests pass unmodified (§10).

The field is stored on every tariff regardless of billing mode rather than
being conditionally present, matching how `fixed_price_chf` and `percentage`
already sit on all tariffs and are read only by the modes that need them. The
serializer does not validate it against `billing_mode`: an ignored value is
harmless, and a validation rule would have to be relaxed the moment a second
billing mode wants a split key.

**Serializer:** `TariffSerializer` — `fields = "__all__"`, so `split_key` is
exposed and writable with no serializer change. Its `validate()` is
billing-mode-aware and needs no new branch.

**Migration:** one `AddField` with default `EQUAL`; existing rows get the
default, no data migration, reversible.

### 5.4 `allocation/windows.py` — `AssignmentWindows`

Window rows grow from 4- to 5-tuples:
`(metering_point_id, valid_from, valid_to, participant_id, allocation_mode)`.
`for_zev()` and `for_participant()` add `allocation_mode` to their `values_list`.

| Method | Behaviour |
|---|---|
| `assignment_at(mp, ts)` | **New.** Returns an `AssignmentResolution \| None` — the assignment covering `ts`, as a frozen dataclass with `holder_id` (literal holder, regardless of mode), `allocation_mode` (`personal`/`community`) and `assignment_id`. `None` only when no assignment covers the timestamp (a true gap). |
| `participant_at(mp, ts)` | **Unchanged** — literal holder semantics (delegates to `participant_on`). |
| `participant_on(mp, day)` | **Unchanged** — feeds the holder-less data-quality flag in `metering/analytics.py`; a community meter is not unassigned. |
| `is_held_by(p, mp, ts)` | **Unchanged** — literal-holder check. Retained for callers that genuinely mean "whose meter is this"; the billing loops stop using it (§7.3). |

Rationale: billing attribution must distinguish "no assignment" (gap, data
quality) from "community-allocated" (valid assignment whose costs are
distributed). Folding payer semantics into `participant_at` — returning `None`
for community windows — would conflate those two states and silently break
every existing caller that treats `None` as unassigned, including the
holder-less data-quality flag added in #396. The explicit resolution object
keeps the three existing lookups and their pinned tests (`allocation/tests.py`)
intact; consumers that must distribute community costs switch to
`assignment_at` and are enforced by the reconciliation fixture (§7.7).

### 5.5 Admin and OpenAPI

- `backend/zev/admin.py`: `ParticipantInline` and
  `MeteringPointAssignmentInline` use explicit `fields` tuples — add
  `allocation_weight` / `allocation_mode`.
- `backend/tariffs/admin.py`: `TariffAdmin` declares `list_display` and
  `list_filter` but no `fields` tuple, so `split_key` reaches the change form
  with no change; add it to `list_filter` so shared-fee tariffs can be found
  by key.
- OpenAPI: drf-spectacular regenerates from the serializers — no manual step,
  but schema snapshots in tests (if any) must be refreshed.

## 6. API contracts

No new endpoints; two response/request shapes gain fields. Base prefix
`/api/v1/zev/`.

| Endpoint | Method | Permission | Change |
|---|---|---|---|
| `/api/v1/zev/metering-point-assignments/` | GET/POST | `IsAuthenticated, MeteringPointAssignmentPermission` | Body/response gain `allocation_mode: "personal" \| "community"` (default `personal`) |
| `/api/v1/zev/metering-point-assignments/{id}/` | GET/PATCH/PUT/DELETE | same | same |
| `/api/v1/zev/participants/` | GET/POST | `IsAuthenticated, BaseZevScopedPermission` | Body/response gain `allocation_weight: string` (decimal, default `"1.0000"`) |
| `/api/v1/zev/participants/{id}/` | GET/PATCH/PUT/DELETE | same | same |
| `/api/v1/tariffs/tariffs/` | GET/POST | `IsAuthenticated, IsZevOwnerOrAdmin` | Body/response gain `split_key: "equal" \| "weight"` (default `equal`) |
| `/api/v1/tariffs/tariffs/{id}/` | GET/PATCH/PUT/DELETE | same | same |

Error behaviour: unchanged — serializer `validate()` surfaces model
`ValidationError`s as 400 with per-field keys (`allocation_mode`,
`allocation_weight`, `valid_from`, …); `allocation_weight <= 0` is rejected by
the field validator.

Whole-ZEV export/import (`zev/transfer/`, added in #410) whitelists its fields
in `zev/transfer/schema.py`: `PARTICIPANT_FIELDS` gains `allocation_weight`,
`ASSIGNMENT_FIELDS` gains `allocation_mode` and `TARIFF_FIELDS` gains
`split_key`, so sharing round-trips an export/import (see the §9 risk row).
The archive `FORMAT_VERSION` does not change: all three fields are additive
with defaults, so an older archive imports as all-personal, weight 1, equal
key — which is exactly today's behaviour.

## 7. Billing engine

### 7.1 Allocation-weight membership helpers

Add two tariff-independent helpers driven by the invoice period, alongside the
existing `_count_active_participants_by_month` (which stays — §7.2 still uses
it for `equal`-keyed fees). The month list comes from `_billable_months` today:

```python
def _allocation_weight_sum_by_month(zev, period_start, period_end) -> dict[date, Decimal]:
    # weight sum per billed month — counted per month so a joiner does not
    # dilute earlier months; read from ZEV membership, never from sibling
    # invoices. Feeds weight-keyed SHARED_* fees and the per-metering-point
    # fees of community meters (§7.2, §7.5).

def _allocation_weight_sum_by_date(zev, period_start, period_end) -> dict[date, Decimal]:
    # weight sum per calendar date, from participant validity ranges
    # (date-granular, matching participant_on). Feeds shared energy, levies
    # and credits (§7.4), so a mid-period joiner pays no share of readings
    # that predate their membership.
```

Share of participant *i* = `allocation_weight_i / weight_sum(date or month)`.
Weights are strictly positive (field validator, §5.2), and any shared window
overlapping the billing period implies at least one eligible participant
(assignment validity is contained in participant validity, enforced by
`MeteringPointAssignment.clean()`), so the denominator can never be zero. With
all weights 1, the month sums equal headcounts and the current equal-split
behaviour is the special case. This keeps "single-participant regeneration
equals a full run" intact.

### 7.2 `SHARED_*` fee modes read their tariff's split key

The `_price_fixed_fees` shared branch keeps its structure — per billed month,
skip months the participant was not a member of, accumulate — and only the
denominator becomes conditional:

```python
if tariff.split_key == SplitKey.WEIGHT:
    shares = _allocation_weight_sum_by_month(participant.zev, period_start, period_end)
    numerator = participant.allocation_weight
else:                                   # SplitKey.EQUAL — today's behaviour
    shares = _count_active_participants_by_month(participant.zev, tariff, period_start, period_end)
    numerator = Decimal("1")
...
    total += unit_price * numerator / shares[month]
```

Both keys stay month-granular and share one eligibility rule: a participant
active for any part of the month shares that month's fee. `EQUAL` is
arithmetically identical to today's `unit_price / count` — the numerator is 1
and the denominator is the same headcount — so existing shared-fee tariffs
produce byte-identical invoices and the 22 existing tests pass unmodified.

`_count_active_participants_by_month` therefore **stays**; it is not replaced
by the weight helpers, which are added alongside it. It keeps its `tariff`
argument (it derives its months from the tariff's validity), while the weight
helpers are tariff-independent because they also serve community energy, which
has no tariff of its own until pricing time.

### 7.3 Personal vs. community is a per-timestamp decision

**This is the load-bearing section.** `_assigned_metering_points` returns
*metering points*, joined through `assignments` and `.distinct()`-ed;
`_readings_in_period` then pulls every reading for those meters in the period,
regardless of which assignment window each reading falls in. A queryset filter
on `allocation_mode` therefore cannot separate personal from community energy
for a meter whose mode changes mid-period (§5.1):

- `.exclude(assignments__allocation_mode=COMMUNITY)` drops the meter entirely,
  because Django excludes the row when *any* joined assignment matches — the
  meter's personal readings from the earlier window are never billed.
- Not filtering at all lets community readings reach `participant_consumption`,
  where a literal `is_held_by` check returns `True` for the holder, billing
  them the full community energy personally *on top of* their weighted share.

So `own_points()` gains **no** allocation-mode filter. Instead the per-reading
gate in the consumption and production loops becomes mode-aware:

```python
resolution = readings.assignment_windows.assignment_at(reading.metering_point_id, ts)
if (
    resolution is None
    or resolution.allocation_mode != AllocationMode.PERSONAL
    or resolution.holder_id != participant.id
):
    continue  # gap, community energy, or somebody else's meter
```

Two consequences to implement deliberately:

- **The skip counters must not count community readings.**
  `skipped_consumption_readings` / `skipped_consumption_kwh` exist to report
  energy that was billed to nobody; community energy is billed to everybody, so
  it must be excluded from the counters as well as from personal pricing.
  Distinguish the three `continue` cases rather than sharing one branch.
- **A community meter's readings legitimately appear in both querysets** — the
  personal one (gated out per timestamp) and the ZEV-level community one. The
  gate is the only thing preventing double counting, which is why §10 asserts
  both halves of a mixed-window meter.

`PeriodReadings` grows four fields:

| Field | Content |
|---|---|
| `community_consumption` | ZEV-level readings of metering points with a `COMMUNITY` assignment overlapping the period, direction IN |
| `community_production` | Same, direction OUT |
| `weight_sum_by_date` | The §7.1 date helper result |
| `weight_sum_by_month` | The §7.1 month helper result |

The per-timestamp pool totals continue to come from the read-model's
`community_totals_by_timestamp`, which covers community meters by construction
(ADR 0013 physical pool) — **only attribution changes, never the denominator.**

### 7.4 Pricing

**Price once, allocate second.** The full physical energy cost, levies,
credits and applicable meter fees of a community meter are calculated exactly
once with the ordinary tariff and ZEV split logic; the resulting amounts and
kWh are then allocated among eligible participants by weight. Nothing in the
community path re-runs tariff resolution per participant, and no
per-participant rounding happens during allocation (quantization is defined in
§9).

In `generate_invoice`, after the personal loops: price each community reading
once (same tariff resolution, same `split_consumption` / `split_production`
against the ZEV totals — which already include community meters), then
allocate the participant's share:

- membership check at the reading's **date**: the billed participant must
  overlap the reading's date (participant validity), else skip — a mid-period
  joiner pays no share of earlier readings, and a leaver's share stops at their
  leave date;
- energy/percentage tariffs → `items_accumulator.add(..., bucket="shared")`
  with `quantity * price * share(date)`;
- shared kWh also accumulate into `local_kwh_acc` / `grid_kwh_acc` /
  `exported_kwh_acc` (weighted), so `total_local_kwh` / `total_grid_kwh` /
  `total_feed_in_kwh` include shared energy;
- shared production credits: production measured at a community metering point
  is allocated to eligible participants with the same weights and the same
  eligibility rule as consumption (explicit decision; a future meter-specific
  allocation rule could override this default). The existing `producer_credit`
  mechanism's symmetric bucket handling applies (`bucket="shared"`).

### 7.5 Per-metering-point fees

- Month ownership decides which side bills each meter-month: for every
  calendar month, the assignment window with the latest `valid_from` among
  those overlapping the month owns it — unambiguous because the non-overlap
  rule (§4) allows one window per metering point per date. The personal
  count (`_count_billable_metering_points_by_month`) bills only months owned
  by a `PERSONAL`-mode window assigned to the participant; the community
  count (`_count_community_metering_points_by_month`) bills only months owned
  by a `COMMUNITY`-mode window. The two counts are therefore disjoint by
  construction: a mid-month mode switch or holder change bills the month
  exactly once, on the side of the owning window — the same per-window care
  as §7.3, not a blanket join exclusion. Both keep their
  `metering_point__is_active=True` filter, and both must fetch every window
  of the metering point so a superseding window can take ownership.
- New: for each per-metering-point tariff, each month, each **active**
  community-owned metering point contributes
  `unit_price * allocation_weight_i / weight_sum(month)` to the participant's
  `bucket="shared"` line of that tariff (inactive community meters bill
  nobody). Meter fees are month-granular: the fee is a monthly charge, so a
  participant active any part of the month shares it.
- `split_key` plays no part here. It is read only by the two `SHARED_*` billing
  modes (§5.3); `PER_METERING_POINT_*` tariffs have no split key, and the cost
  being divided belongs to a community *meter*, which always allocates by
  weight (§1.1). A per-assignment key would be the place to make that
  configurable, and is out of scope (§3).

### 7.6 Line items and descriptions

- `ItemAccumulator` entries expose their bucket; `_build_item_payloads` emits it.
- `_build_description` appends a community marker for `bucket="shared"` lines:
  energy mode → `"{name} ({marker})"`; month-count modes → inside the existing
  parentheses, `"{n} {suffix}, {marker}"`.
- New key `community_marker` in `DESCRIPTION_TRANSLATIONS`, four locales:
  de `"Gemeinschaftsanteil"`, fr `"Part communautaire"`,
  it `"Quota comunitaria"`, en `"Community share"`.

### 7.7 Consumer migration (all must follow)

Since #412 the fetch/resolve/split core lives in `allocation/read_model.py`:
`community_totals_by_timestamp` is the physical pool, and
`iter_allocated_readings` resolves each (metering point, timestamp) group to
its holder via `windows.participant_at` and splits it against the pool. That
makes the read-model the chokepoint: swap that call for `assignment_at`, have
`AllocatedReading` carry the allocation mode, and keep the literal `holder_id`
for provenance — consumers must then distribute community readings by weight
instead of attributing them to the holder.

| Consumer | Change |
|---|---|
| `allocation/read_model.py` | `AllocatedReading` gains the allocation mode; holder resolution switches from `participant_at` to `assignment_at` |
| `invoices/pdf_stats.py` | Both `iter_allocated_readings` loops currently skip `holder_id is None`; community-marked readings get distributed into each participant's totals by weight |
| `metering/analytics.py` | The six `participant_at` sites switch to `assignment_at` and distribute community readings by date-granular weight share (one extra query: participant validity + weights). The `participant_on` data-quality site keeps literal-holder semantics — a community meter is not unassigned (§5.4) |
| `invoices/annual_statement.py` | Monthly tables include the participant's share (two `is_held_by` sites + a community loop) |
| `invoices/pdf_charts.py` | Hourly profile includes weighted community energy (one `is_held_by` site) |

Enforcement: `invoices/test_allocation_reconciliation.py` is extended with a
community meter in the fixture — every consumer-vs-engine comparison diverges
until all consumers are migrated. `allocation/test_read_model.py` pins the
read-model contract. `invoices/test_allocation_query_counts.py` pins
per-consumer query counts — a new shared fetch that breaks the single-fetch
invariant goes red there.

## 8. Frontend

### 8.1 Metering points

- **`frontend/src/features/meteringPoints/MeteringAssignmentFormModal.tsx`:**
  new select `allocation_mode` (personal/community) in the controlled form
  state and layout, default `personal` (the modal is a controlled MUI form —
  `form`/`setForm` props, no zod/react-hook-form).
- **`frontend/src/features/meteringPoints/MeteringPointsList.tsx`:** badge on
  assignment rows where the current assignment is community.
- i18n (4 locales, `frontend/src/i18n/locales/{de,fr,it,en}.ts`), under the
  `pages.meteringPoints.assignForm` block: `allocationMode`,
  `allocationModePersonal`, `allocationModeCommunity`, `allocationModeHint`,
  plus `pages.meteringPoints.communityBadge`.
- Gate: selector ships together with the engine change (not in isolation).

### 8.2 Participants

- **`frontend/src/features/participants/ParticipantFormModal.tsx`:** numeric
  input `allocation_weight` (zod: `.positive()`), shown as a plain decimal
  weight — the input is **never** a percentage, per-mille or "/1000" — with a
  hint; default empty → backend default `1`.
- Participants list: informational indicator showing the computed share of the
  current allocation key, e.g. `"25.0000 % — 1.0000 of 4.0000 weights"`. The
  derived share may be displayed as a percentage; only the weight *input* is
  restricted to a plain decimal. Not a sum constraint.
- i18n under `pages.participants`: `form.allocationWeight`,
  `form.allocationWeightHint`, `weightShare`, `weightShareHint`.

### 8.3 Tariffs: split-key selector

**File:** `frontend/src/features/tariffs/TariffFormModal.tsx` (form state in
`useTariffForms.ts`).

- New select `split_key` (`equal` / `weight`), **shown only when
  `billing_mode` is `shared_monthly_fee` or `shared_yearly_fee`** — the field
  is meaningless for the other six modes and the form already switches inputs
  on billing mode. Default `equal`.
- The existing shared-fee hint (`pages.tariffs.form.sharedFeeHint`) says the
  amount is split *gleichmässig* (equally). That stays correct for `equal` and
  becomes wrong for `weight`, so the hint becomes key-dependent: keep the
  current string for `equal` and add a second one for `weight`, rather than
  rewording the existing key to cover both vaguely.
- i18n under `pages.tariffs.form`: `splitKey`, `splitKeyEqual`,
  `splitKeyWeight`, `sharedFeeHintWeight` (the existing `sharedFeeHint` keeps
  its current text and meaning).

### 8.4 Locale parity

`frontend/tests/locale-parity.test.ts` (added in #452) asserts that de/fr/it
match the `en` key structure exactly and that `{{placeholder}}` names agree.
Every key added in §7.6 and §8.1–§8.3 must therefore land in all four locale
files in the same commit, or `npm run test:unit` fails.

### 8.5 TypeScript types

**File:** `frontend/src/types/api.ts` — shorthand deltas on six shapes:

```typescript
// MeteringPointAssignment / MeteringPointAssignmentInput gain:
    allocation_mode?: 'personal' | 'community'   // defaults 'personal'
// Participant / ParticipantInput gain:
    allocation_weight?: string                   // decimal string, default "1.0000"
// Tariff / TariffInput gain:
    split_key?: 'equal' | 'weight'               // defaults 'equal'
```

### 8.6 API client functions

No new functions in either client — the existing calls carry the new fields via
the extended input types:

- `frontend/src/lib/api/zev.ts`: `createMeteringPointAssignment` /
  `updateMeteringPointAssignment` / `createParticipant` / `updateParticipant`
- `frontend/src/lib/api/tariffs.ts`: the tariff create/update calls

## 9. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A meter whose mode changes mid-period is double-billed or silently unbilled | High | §7.3: the decision is per timestamp via `assignment_at`, never a queryset filter; asserted from both sides by `test_mixed_window_meter_bills_personally_then_shares` |
| Rounding does not conserve exactly (N-way rappen division) | Medium | Existing documented convention: each participant's share is quantized per line item at line build, rounded half-up, and the sub-rappen remainder is dropped ("shared fees already collect 99.99 of 100.00"). The conservation test asserts Σ shares vs. source < 1 rappen per line; cumulative drift is bounded by lines × 1 rappen per invoice. Exact conservation via a batch allocator stays an ADR 0013 follow-up |
| Editing a weight retroactively changes regenerated periods | Medium | Documented (§3) + UI hint on the regeneration confirmation; drafts regenerate freely, finalized invoices are protected by existing engine guards. Blast radius is bounded by `split_key`: community meters and `weight`-keyed fees only — an `equal`-keyed shared fee never moves |
| A `SHARED_*` tariff is switched to `weight` without anyone noticing the fees move | Low | The selector appears only for the two shared modes and defaults to `equal` (§8.3); the change is an ordinary audited tariff mutation (`AuditedUpdateMixin` on `TariffViewSet`), so the before/after shows in the audit log with the rest of the tariff diff |
| N-fold refetch of community readings per participant in `generate_invoices_for_zev` | Low | Consistent with existing ZEV-total behaviour; memoize per (zev, period) if trivial; query-count pins live in §7.7 |
| Export/import silently drops the new fields | Low | `zev/transfer/schema.py` whitelists gain `allocation_weight` / `allocation_mode` / `split_key` in phase 1 (§6); older archives import as all-personal, weight 1, equal key |

## 10. Test plan

Existing suites: the 22 shared-fee tests and 6 query-count tests stay green
**unmodified**; the 10 reconciliation tests keep their existing assertions with
a community meter added to their shared fixture (§7.7). New backend tests (46):

### Backend — `allocation/tests.py`

**`SharedWindowSemanticsTests`** (5 tests):

| Test | Asserts |
|---|---|
| `test_assignment_at_resolves_mode_and_holder` | Resolution object: holder_id + allocation_mode + assignment_id |
| `test_participant_at_stays_literal_for_community_windows` | `participant_at` unchanged: returns the literal holder |
| `test_is_held_by_stays_literal_for_community_windows` | `is_held_by` unchanged: True for the holder |
| `test_assignment_at_returns_none_only_for_true_gaps` | `None` only when no assignment covers the timestamp |
| `test_personal_windows_unaffected` | Regression guard |

### Backend — `zev/tests.py`

**`AllocationModelAndApiTests`** (6 tests):

| Test | Asserts |
|---|---|
| `test_assignment_allocation_mode_defaults_to_personal` | Model default |
| `test_assignment_accepts_community_allocation_mode_via_api` | POST round-trip, 201 |
| `test_participant_allocation_weight_defaults_to_one` | Model default |
| `test_zero_and_negative_allocation_weight_rejected` | PATCH → 400 with field error (MinValueValidator) |
| `test_allocation_mode_exposed_in_assignment_serializer` | GET shape |
| `test_allocation_weight_exposed_and_writable_in_participant_serializer` | GET/PATCH shape |

### Backend — `tariffs/tests.py`

**`SplitKeyModelAndApiTests`** (3 tests):

| Test | Asserts |
|---|---|
| `test_split_key_defaults_to_equal` | Model default on every billing mode |
| `test_split_key_exposed_and_writable_via_api` | GET/PATCH round-trip through `fields = "__all__"` |
| `test_split_key_is_accepted_but_inert_on_non_shared_modes` | Storing `weight` on an energy tariff changes no amount (§5.3: read only by the two shared modes) |

### Backend — `metering/tests.py`

**1 test** — extends the existing data-quality suite:

| Test | Asserts |
|---|---|
| `test_community_meter_does_not_look_unassigned_in_data_quality` | `participant_on` stays literal: community window flags no unassigned days |

### Backend — `invoices/test_shared_fee.py`

**`SplitKeyedSharedFeeTests`** (8 tests):

| Test | Asserts |
|---|---|
| `test_equal_key_ignores_weights_entirely` | **The isolation guarantee:** unequal weights set, `split_key = equal`, amounts identical to today's headcount split |
| `test_weight_key_splits_by_weight` | Golden franc values with `split_key = weight` |
| `test_split_key_defaults_to_equal` | A tariff created without naming a key bills as it does today |
| `test_two_shared_tariffs_can_use_different_keys` | One `equal` and one `weight` tariff in the same ZEV, same invoice, both correct — the case this field exists for |
| `test_default_weights_reproduce_equal_split_under_weight_key` | With all weights 1, `weight` and `equal` agree |
| `test_joiner_shifts_weight_sum_only_from_their_own_month` | Per-month denominator |
| `test_tiny_weight_bills_almost_nothing` | Negligible-weight member (0.0001 of 1.0001) |
| `test_an_indivisible_weighted_share_leaves_the_rappen_shortfall` | Rounding convention |

### Backend — `invoices/test_shared_metering.py` (new file)

**`SharedMeteringEngineTests`** (17 tests):

| Test | Asserts |
|---|---|
| `test_shared_consumption_is_billed_to_every_member_by_weight` | Golden values incl. levies |
| `test_the_holder_pays_their_share_like_everyone_else` | No holder special case |
| `test_sole_participant_carries_the_shared_meter_alone` | N=1 |
| `test_shared_energy_conservation_within_rounding` | Σ shares vs. full amount, < 1 rappen |
| `test_shared_production_credits_every_member_symmetrically` | Symmetric split |
| `test_shared_meter_part_of_period_only_shares_that_window` | Time-bounded sharing |
| `test_mixed_window_meter_bills_personally_then_shares` | **§7.3 both halves:** a meter personal in month 1 and community in month 2 bills the holder in full for month 1 and only a weighted share for month 2 — no lost readings, no double billing |
| `test_community_readings_are_not_counted_as_skipped` | §7.3: skip counters exclude community energy |
| `test_per_metering_point_fee_splits_shared_meters_and_excludes_holder` | §7.5 both halves |
| `test_inactive_shared_meter_bills_nobody` | `is_active` mirroring |
| `test_joiner_does_not_pay_for_community_energy_before_join_date` | Date-granular numerator |
| `test_leaver_does_not_pay_for_community_energy_after_leave_date` | Date-granular numerator |
| `test_weighted_energy_and_fee_use_their_respective_time_granularity` | Energy by date, fees by month |
| `test_community_production_uses_same_eligibility_rule` | Production follows consumption weights/eligibility |
| `test_invoice_kwh_totals_include_shared_energy` | §7.4 totals |
| `test_shared_line_description_carries_the_community_marker` | All four locales |
| `test_single_participant_regeneration_equals_full_run` | ZEV-data-only shares |

### Backend — `invoices/test_allocation_reconciliation.py`

Fixture extended with a community meter; new (2 tests):

| Test | Asserts |
|---|---|
| `test_all_consumers_reconcile_with_a_community_meter` | analytics/pdf_stats vs. engine |
| `test_community_meter_energy_is_attributed_to_no_single_holder` | No holder attribution anywhere |

### Backend — `allocation/test_read_model.py`

**`SharedReadModelTests`** (3 tests) — pins the §7.7 read-model contract:

| Test | Asserts |
|---|---|
| `test_community_readings_carry_mode_and_literal_holder` | `iter_allocated_readings` contract: holder_id + `allocation_mode == "community"` |
| `test_community_readings_split_against_the_physical_pool` | Split math unchanged for community meters |
| `test_community_readings_are_distinct_from_gap_readings` | Consumers can tell the two cases apart |

### Backend — `invoices/test_pdf.py`

**1 test:** `test_shared_lines_render_with_marker` — marker text present per
invoice language.

### Frontend

- Build and type checks: `npm run build`
- Unit tests: `npm run test:unit` — includes `locale-parity.test.ts` (§8.4)
- Manual: create community assignment → badge visible; invoice PDF shows
  marker; participant weight edit → regenerated draft shares change.

## 11. Implementation phasing

1. **Terminology, migration, API, assignment resolution** (§5, §6): the three
   migrations (`allocation_mode`, `allocation_weight`, `split_key`),
   serializers, `assignment_at`, `zev/transfer/schema.py` whitelists, admin
   registration. No billing change — every default reproduces current
   behaviour, which is what makes this phase independently shippable.
2. **Allocation primitive and tests** (§7.1): date/month weight-sum helpers,
   share math, conservation and granularity tests; reconciliation fixture
   extended with a community meter here. `_count_active_participants_by_month`
   is left alone.
3. **Read model and all consumers** (§7.7): `AllocatedReading` mode, migrate
   analytics, pdf_stats, statements and charts until reconciliation is green.
4. **Invoice engine** (§7.2–§7.6): the per-timestamp gate first (§7.3), then
   allocate community energy, credits, fixed fees and meter-point charges via
   the primitive. The `split_key` branch in `_price_fixed_fees` (§7.2) can land
   independently of the community-meter work — it touches a different code
   path — and is the cheapest half to review.
5. **Frontend, documentation, export/import validation** (§8, §6): ship only
   once invoice and reconciliation tests are green.

The baseline spec updates listed in §3 land with the implementation PR.
