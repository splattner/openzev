# Feature Spec: Metering points with generation behind the meter

- Spec ID: SPEC-2026-behind-the-meter-generation
- Status: Completed
- Scope: Minor
- Type: Change
- Owners: Sebastian Plattner
- Created: 2026-09-30
- Target Release: 1.21.0
- Related Issues: —
- Related ADRs: [0013](../adr/0013-shared-allocation-service.md) (readings attributed at their timestamp)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

In a vZEV the producer's PV system usually sits **behind** their grid
connection meter. That meter is bidirectional and records only what crosses
the connection point:

- `out`: the PV **surplus** exported after the household's own use,
- `in`: grid draw, which only happens while there is no surplus.

Everything the household consumes directly from its own PV never reaches the
meter. This is net (surplus) metering, in German *Überschussmessung*. It is
not gross production metering, which needs a separate production meter.

Billing is unaffected and correct. In a vZEV only energy that crosses the
connection point can be shared, and behind-the-meter self-consumption is
legally outside the community.

The **statistics** are misleading, though. Example: vZEV Hölzliackerweg 1,
July to August 2026.

| Participant | `consumed_kwh` | `produced_kwh` | self-sufficiency |
|---|---|---|---|
| Consumer A | 1058 | 0 | 31 % |
| Consumer B | 1013 | 0 | 33 % |
| Producer (net meter) | 308 | 3791 | **1.5 %** |

The producer's 308 kWh is only their residual grid draw, and the 3791 kWh is
only the surplus. The 1.5 % suggests the producer is almost entirely
grid-dependent, when the opposite is true. The ZEV-wide rates
(self-consumption 17.6 %, self-sufficiency 28.1 %) are arithmetically right
for what the ZEV exchanges. But PV owners read them as the plant's
*Eigenverbrauchsquote* / *Autarkiegrad*, and those are much higher.

**Outcome:**

1. A metering point can be marked as having **generation behind the meter**.
2. A participant who holds such a meter no longer gets a self-sufficiency rate
   anywhere: dashboard, annual report, annual statement PDF, or MCP. They see
   `—` and a short explanation instead.
3. Wherever the ZEV has such a meter, the ZEV-wide figures carry a note
   explaining what they measure: production is the exported surplus, and the
   rates describe energy exchanged at the connection points.

ZEV-wide kWh totals and the rates themselves are **not** recomputed or
excluded. The flows are real, and billing depends on them.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `MeteringPoint.has_behind_meter_generation` (bool) + migration |
| API | Field on `MeteringPointSerializer` with validation; flags on dashboard, annual report, and MCP payloads |
| Analytics | `owner_dashboard_summary`, `participant_dashboard_summary`, `build_annual_report`, the annual statement's monthly data |
| PDFs | Annual statement: rate `—` plus a note for flagged participants |
| MCP | `consumption_summary` (and any other MCP tool exposing `local_share_pct` / self-sufficiency) |
| Transfer archive | Field exported and imported; older archives import as `false` |
| Frontend | Metering-point form checkbox + list badge; Energy balance, participant dashboard, and annual report render `—` and notes |
| Docs | User guide metering-point and energy/report chapters; baseline specs (see §10) |

### Out of scope

- Importing gross production data (an inverter export or a separate production
  meter) to compute the producer's true Eigenverbrauchsquote / Autarkiegrad.
  This is the follow-up specified in
  [2026-10-supplementary-energy-data.md](2026-10-supplementary-energy-data.md). The flag
  introduced here is its anchor.
- Any change to billing, allocation (`split_consumption` /
  `split_production`), invoices, or invoice PDFs. Invoice line items stay
  exactly as they are.
- Auto-detecting the flag from reading patterns.
- Excluding flagged meters from ZEV-wide totals or rates.

## 3. Actors, permissions, and ZEV scope

No change. The field is edited through the existing metering-point endpoints
with their existing permissions (admin: any ZEV; `zev_owner`: own ZEVs;
`participant`: read-only on their own). All new response flags follow the
visibility of the payload they sit in.

## 4. Data model

### 4.1 MeteringPoint

**Model:** `zev.models.MeteringPoint`, new field:

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `has_behind_meter_generation` | `BooleanField` | `False` | `help_text="Generation (e.g. PV) sits behind this meter, so it records only the surplus fed in and the residual grid draw (net / surplus metering)."` |

Migration: `zev/00NN_meteringpoint_has_behind_meter_generation.py`, which only
adds the field. Existing rows get `False`, so there is no data migration.

**Validation:** `has_behind_meter_generation=True` requires `meter_type` to be
`bidirectional` or `production`. A consumption-only meter cannot have surplus
behind it. This is enforced in `MeteringPoint.clean()` and in
`MeteringPointSerializer.validate()`, using the effective `meter_type`
(incoming value or instance value on partial update). On violation:
`400 {"has_behind_meter_generation": ["Only bidirectional or production metering points can have generation behind the meter."]}`.

**Serializer:** `MeteringPointSerializer` uses `fields = "__all__"`, so the
field is exposed and writable automatically. Only the validation is added.

### 4.2 Derived notion: "net-metered participant"

A participant is **net-metered in a window** if, for at least one reading of a
flagged metering point inside the window, `_distribute_reading` attributes
that reading to them through a **personal** assignment.

- Community-mode assignments never make a participant net-metered. Their
  readings are split by weight, so no single participant's rate is distorted
  by behind-the-meter use.
- A holder who switches meters mid-window is net-metered for the whole window.
  The rate is suppressed rather than partially shown, because a partial rate is
  still misleading.

Implement this once, as a helper in `metering/analytics.py`:

```python
def net_metered_participant_ids(windows, readings_qs) -> set[str]:
    """Participants who personally held a meter with generation behind it
    for at least one reading in ``readings_qs``."""
```

It collects the flagged metering-point ids among `readings_qs`
(`MeteringPoint.objects.filter(id__in=..., has_behind_meter_generation=True)`),
then resolves `windows.assignment_at(mp, ts)` for each distinct `(mp, ts)` of
those meters with `allocation_mode == PERSONAL`. One query per flagged meter
over its distinct timestamps is acceptable. Short-circuit with no extra
queries when the ZEV has no flagged meter, which will be the common case.

## 5. API contracts

No new endpoints. Additive response fields only: existing fields keep their
meaning and type, except the per-participant rates listed below, which become
`null` for net-metered participants.

### 5.1 Metering points

`/api/v1/zev/metering-points/` (existing `MeteringPointViewSet`):
`has_behind_meter_generation: boolean` on read and write, validated per §4.1.

### 5.2 Owner / admin dashboard (`owner_dashboard_summary`)

- Each `participant_stats[]` entry gains
  `has_behind_meter_generation: boolean` (§4.2).
- Top level gains `zev_has_behind_meter_generation: boolean`: true when any
  metering point with readings in `qs` is flagged.
- kWh fields are unchanged.

### 5.3 Participant dashboard (`participant_dashboard_summary`)

- Top level gains `has_behind_meter_generation: boolean`: the current
  participant is net-metered in the window.
- Each `zev_participant_stats[]` entry gains
  `has_behind_meter_generation: boolean`.
- Top level gains `zev_has_behind_meter_generation: boolean`.

### 5.4 Annual report (`/api/v1/invoices/invoices/annual-report/`)

- `participants[]` gains `has_behind_meter_generation: boolean`. When it is
  `true`, `self_sufficiency_rate` is `null`. `from_zev_kwh` and the savings
  are unchanged.
- Top level gains `has_behind_meter_generation: boolean`: any flagged meter
  had readings in the year.
- `totals`, `previous_totals`, and `months` are unchanged.

### 5.5 Annual statement (participant PDF)

In `invoices/annual_statement.py`, when the statement's participant is
net-metered in the year:

- every `monthly_data[].self_sufficiency_pct` and
  `totals.self_sufficiency_pct` becomes `None`, and the template renders `—`;
- context gains `has_behind_meter_generation: True`, and the template renders
  a note below the monthly table (new translation key `behind_meter_note` in
  all four languages of `ANNUAL_TRANSLATIONS`):
  - de: "Ihre Photovoltaikanlage liegt hinter dem Zähler. Erfasst werden nur der eingespeiste Überschuss und der Netzbezug; Ihr Eigenverbrauch direkt ab Anlage ist nicht enthalten. Deshalb wird keine Autarkie ausgewiesen."
  - en: "Your PV system sits behind your meter. Only the surplus fed in and the energy drawn from the grid are recorded; what you use directly from your system is not included. No self-sufficiency rate is therefore shown."
  - fr and it: equivalent translations.
- The sample context (`build_sample_annual_statement_context`) keeps
  `has_behind_meter_generation: False`. The field catalog
  (`field_catalog_data.py`) documents the new variable
  `{{ has_behind_meter_generation }}` and the new `tr` key.

If the monthly chart SVG plots the rate, it skips `None` values.

### 5.6 MCP

`consumption_summary`: each `participants[]` entry gains
`has_behind_meter_generation`, and `local_share_pct` becomes `null` when it is
true. `totals` gains `has_behind_meter_generation` — the ZEV-wide flag for the
whole-ZEV call, or the selected participant's own flag (with
`self_sufficiency_pct` also nulled) when `participant_id` is given. Every
other MCP tool that returns a per-participant local share or self-sufficiency
gets the same treatment: `consumption_profile`'s response gains
`has_behind_meter_generation` (from `compute_hourly_profile`'s own flag) and
nulls `local_share_pct` when it is true. `explain_invoice`'s `local_share_pct`
is the invoice's actually-billed local/grid split, not a consumption
self-sufficiency stat, and stays untouched — billing and invoice line items
are unaffected by this feature (§2 out of scope). The tool descriptions of
`consumption_summary` and `consumption_profile` gain one sentence: "Meters
with generation behind them record only surplus and residual grid draw; the
holder's local share is null."

### 5.7 Transfer archive

The whole-ZEV export writes `has_behind_meter_generation` for each metering
point. Import reads it with default `False` when absent, so older archives
stay importable. If the archive has a format version, do not bump it for an
additive field with a default, unless the archive spec requires it.

## 6. Async and integration behavior

None. The annual-statement ZIP export job renders the same PDF, so it picks up
§5.5 automatically.

## 7. Frontend

### 7.1 Metering-point form and list

- The metering-point create/edit form gets a checkbox **"Generation behind the
  meter (surplus metering)"**. It is shown and enabled only when `meter_type`
  is `bidirectional` or `production`. Changing the type to `consumption`
  clears it. A help text below it reads: "Tick this when a PV system sits
  behind this meter, so the meter only records the surplus fed in and the
  grid draw."
- Wherever `meter_type` is displayed in a metering-point list/table, flagged
  meters show a small badge ("Surplus metering") next to the type.
- Server validation errors on the field surface like other field errors.

### 7.2 Energy balance (owner/admin `DashboardPage`)

- Participant table / Sankey rows with `has_behind_meter_generation` show `—`
  for self-sufficiency / local share, and a badge or info icon with the tooltip
  `behindMeter.participantHint`. Consumption stays as is, but its tooltip
  labels it as grid draw.
- The per-participant rate the frontend computes (`fromZevRate` or
  equivalent, from `from_zev_kwh / total_consumed_kwh`) is suppressed for
  flagged rows. Suppress it in the frontend: the backend sends kWh, not a rate,
  on this payload.
- When `zev_has_behind_meter_generation` is true, an info note below the
  ZEV-wide KPI row reads `behindMeter.zevNote`: "Some metering points have a
  PV system behind them. For those, production means the surplus fed in, and
  the rates describe energy exchanged at the connection points, not the plant's
  own self-consumption."
- When a single net-metered participant is selected, their own
  self-sufficiency KPI shows `—` with the hint.

### 7.3 Participant dashboard

If `has_behind_meter_generation` is true, the participant's own "from ZEV"
share / self-sufficiency KPI shows `—` with `behindMeter.ownHint`: "Your PV
system sits behind your meter; your own use of it is not measured, so no rate
is shown." Their consumption KPI is labelled as grid draw via the hint. The
ZEV-wide note from §7.2 is shown when `zev_has_behind_meter_generation` is
true.

### 7.4 Annual report (`AnnualReportSection`)

- `ParticipantSavingsCard`: `self_sufficiency_rate` is already `null` for
  flagged rows, so it renders `—`. Add the badge/info icon with
  `behindMeter.participantHint`.
- `AnnualReportKpis`: when `has_behind_meter_generation` is true, render the
  `behindMeter.zevNote` note under the KPI row.

### 7.5 Components and i18n

Reuse one small shared component for the badge/hint, e.g.
`frontend/src/components/BehindMeterBadge.tsx`, with an info icon, tooltip,
and accessible label. Put the ZEV note in the existing muted note / hint style.
Add no new colour literals.

i18n keys in all four locales (`de`, `fr`, `it`, `en`):
`behindMeter.{badge, participantHint, ownHint, zevNote}`, and for the form:
`meteringPoints.form.{behindMeterGeneration, behindMeterGenerationHelp}`.
Match each namespace to where the neighbouring keys actually live.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
// MeteringPoint
has_behind_meter_generation: boolean

// owner dashboard participant stat, participant dashboard zev_participant_stats
has_behind_meter_generation: boolean
// owner + participant dashboard summaries
zev_has_behind_meter_generation: boolean
// participant dashboard summary
has_behind_meter_generation: boolean

// AnnualReportParticipant
has_behind_meter_generation: boolean
// AnnualReport
has_behind_meter_generation: boolean
```

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Owner forgets to set the flag | Medium | Checkbox with help text in the form; the user guide explains when to tick it |
| Extra queries slow the dashboard / annual report | Low | Short-circuit when the ZEV has no flagged meter; resolve holders only for flagged meters |
| Users expect the rates to change | Low | Rates are deliberately unchanged; the ZEV note explains their meaning |
| Suppressing a partially-held participant's rate | Low | Documented rule (§4.2): any personal holding in the window suppresses it |

## 9. Test plan

### Backend

`zev/tests.py` (`MeteringPointBehindMeterGenerationTests`, new class, 4 tests):

| Test | Asserts |
|---|---|
| `test_behind_meter_generation_defaults_false` | new meter has `False` |
| `test_behind_meter_generation_allowed_for_bidirectional_and_production` | 2 writes (via the API) succeed |
| `test_behind_meter_generation_rejected_for_consumption` | 400, `has_behind_meter_generation` field error |
| `test_partial_update_to_consumption_with_flag_set_is_rejected` | PATCH `meter_type=consumption` on a flagged meter → 400 |

`metering/tests.py` (`BehindMeterGenerationDashboardTests`, new class, 4 tests):

| Test | Asserts |
|---|---|
| `test_owner_dashboard_marks_net_metered_participant` | flagged holder `has_behind_meter_generation` true, others false, `zev_has_behind_meter_generation` true |
| `test_owner_dashboard_without_flag_is_unchanged` | all false; kWh unchanged against a baseline |
| `test_community_assignment_on_flagged_meter_marks_nobody` | community-mode flagged meter → all false, top-level flag still true |
| `test_participant_dashboard_marks_own_net_metering` | participant's own flag, `zev_participant_stats` per-row flags, and `zev_has_behind_meter_generation` |

`invoices/test_annual_report.py` (`AnnualReportContentTests`, +2):

| Test | Asserts |
|---|---|
| `test_net_metered_participant_has_null_rate_and_flag` | rate `null`, flag true, kWh and savings unchanged; top-level flag true |
| `test_totals_are_unchanged_by_the_flag` | `totals` equal before/after toggling the flag on the same reading set |

`invoices/test_reports.py` (`AnnualStatementBehindMeterGenerationTests`, new class, 2 tests): a
net-metered participant's `_compute_monthly_data` returns `None` rates and
`totals["has_behind_meter_generation"] = True`, and
`generate_annual_statement_pdf` still renders a PDF
(`test_net_metered_participant_has_null_rates_and_flag`); a non-flagged
participant is unchanged (`test_non_flagged_participant_is_unchanged`).

`invoices/test_allocation_query_counts.py`: `test_annual_statement_monthly_data_query_count`
and `test_owner_dashboard_query_count` budgets raised by one query each — the
short-circuiting flagged-metering-point lookup `net_metered_participant_ids`
performs when the ZEV has no flagged meter (still zero window resolution).

`zev/test_transfer.py` (+3, more than the originally planned +2 because the
absent-field case is its own test rather than folded into the round-trip
one): `test_export_contains_the_behind_meter_generation_field`
(`ArchiveShapeTests`) — export writes the field per point;
`test_behind_meter_generation_round_trips_and_defaults_false_when_absent` and
`test_metering_points_json_without_the_field_imports_as_false`
(`RoundTripTests`) — `true` round-trips, and an archive missing the field
(rewritten via `rewrite_archive`) imports every point as `False`.

`mcp_server/tests/test_tools.py` (+2, more than the originally planned +1
because `consumption_profile` needed the same treatment per §5.6):
`TestConsumptionSummary.test_net_metered_participant_has_null_local_share` —
the ZEV-wide call returns the flag and a `null` `local_share_pct` for a
net-metered participant, and `totals.has_behind_meter_generation: true`;
`TestConsumptionProfile.test_net_metered_participant_has_null_local_share` —
the participant's own profile returns `has_behind_meter_generation: true` and
`local_share_pct: null`.

### Frontend

- `tests/metering-point-form-behind-meter.test.ts` (new, 3 tests): the
  metering-point form shows the checkbox only for bidirectional/production and
  clears the flag (and hides the checkbox) on switch to consumption.
- `tests/reports-page.test.ts`: `makeReport()` and its participant fixtures
  gain `has_behind_meter_generation`; a new test renders `—` plus the
  `behindMeter.badge` for a flagged participant row and the
  `behindMeter.zevNote` note under the KPI row when the top-level flag is set.
- `tests/dashboard-behavior.test.ts`: a new test asserts a flagged
  participant's Energy balance row renders `—` plus the badge while an
  unflagged row is unaffected, and the ZEV-wide note appears.
- `tests/metering-point-forms.test.ts`: `defaultMeteringPointForm()`'s
  expected shape gains `has_behind_meter_generation: false`.
- `npm run lint`, `npm run lint:style`, hex sweep, `npm run test:unit`,
  `npm run build` — all green except three pre-existing, unrelated failures
  (`tests/pdf-preview.test.ts`, two in `tests/participant-documents.test.ts`,
  both about blob/object-URL reuse under jsdom's opaque-origin restriction,
  reproducible on `main` before this change).
- Dev stack: set the flag on a producer's meter; check the Energy balance,
  the Reports page, and the participant dashboard at desktop width and 400 px;
  no console errors.

### Acceptance criteria

- [x] An owner can mark a bidirectional or production metering point as having generation behind the meter; consumption meters cannot be marked.
- [x] A participant personally holding a flagged meter shows no self-sufficiency / local-share rate (`—` + hint) on the Energy balance, the participant dashboard, the annual report, the annual statement PDF, and in MCP.
- [x] ZEV-wide kWh totals, rates, invoices, and savings are identical with the flag on or off.
- [x] A ZEV with a flagged meter shows the explanatory note next to its ZEV-wide figures.
- [x] The flag survives a transfer-archive export/import; older archives import with `false`.
- [x] All user-facing text is translated in de/fr/it/en.

## 10. Documentation to update

- Baseline `2026-03-metering-point-management.md`: §3.1 field table, and
  validation.
- `2026-09-annual-zev-report.md`: response shape, participant rate rule, TS
  types, tests.
- `2026-03-invoice-lifecycle-and-communication.md` or wherever the annual
  statement PDF context is specified: the new context key and note.
- `2026-08-zev-transfer-archive.md`: metering-point fields.
- `2026-09-mcp-server.md`: `consumption_summary` shape.
- Whichever baseline documents the dashboard payloads
  (`2026-03-metering-import-and-quality.md` or the tariffs/billing spec):
  the new flags.
- User guide: the metering-point chapter (when to tick the box, with an
  explanation of surplus vs gross metering) and the energy balance / reports
  chapters (what the note means).
