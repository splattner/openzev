# Feature Spec: LEG (Lokale Elektrizitätsgemeinschaft) Billing Model

- Spec ID: SPEC-2026-06-leg-billing-model
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: —
- Created: 2026-06-09
- Target Release: —
- Related Issues: —
- Related ADRs: —
- Impacted Areas: backend | frontend | async jobs | docs

---

## 1. Problem and outcome

A **Lokale Elektrizitätsgemeinschaft (LEG)** is a new legal entity introduced in Swiss energy law (EnG Art. 17a ff.) effective 2026. It differs fundamentally from a vZEV:

| Dimension | vZEV | LEG |
|---|---|---|
| Grid connection | Single shared connection; ZEV operator bills all energy | Each participant has their **own** grid connection |
| Billing scope | ZEV operator invoices local + grid kWh + fees | LEG operator invoices **only internally-exchanged energy** + service fee |
| Grid and feed-in | ZEV operator settles with grid operator; charges on to participants | Grid operator settles each participant's import/export **directly**; LEG operator does not touch that balance |
| Metering source | Participant-level meters imported by ZEV operator | Grid operator provides an aggregated exchange-pool value; participant meters required at 15-min resolution |
| Regulatory ID | None required | Requires official LEG registration number and grid operator contract reference |

The current `InvoiceViewSet` / `engine.py` billing pipeline always charges both local and grid energy and issues feed-in credits. Running this pipeline against an LEG community would produce legally incorrect invoices. This spec defines the minimum changes needed to support LEG billing correctly.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| `ZevType` enum | Add `leg` choice |
| `Zev` model | Add `leg_registration_number` and `leg_grid_operator_contract_ref` fields |
| `Participant` model | Add `participant_role` field (`consumer`, `producer`, `prosumer`) |
| `MeteringPoint` model | Add `exchange_pool` meter type for grid-operator-provided aggregated value |
| `EnergyType` enum | Add `leg_exchange` value for internally-traded kWh |
| `InvoiceItem.ItemType` | Add `leg_exchange_energy` item type |
| Billing engine | New `engine_leg.py` with LEG-specific allocation: charge only internally-exchanged kWh; skip grid/feed-in billing |
| Invoice generation dispatch | `engine.py` / `generate_invoice()` dispatches to LEG engine when `zev.zev_type == ZevType.LEG` |
| API serializers | Expose new fields; LEG-only fields validated only when `zev_type == leg` |
| Frontend | ZEV settings form: show LEG fields conditionally; participant form: show role field; invoice display: show LEG exchange line |
| PDF template | LEG invoice variant: omit grid/feed-in sections; show exchange pool kWh + service fee |
| Tariff model | Allow `energy_type = leg_exchange` on `Tariff`; validate this is only set on LEG ZEVs |

### Out of scope

- Automated SDAT-CH import of the grid-operator-provided exchange pool value (manual upload sufficient for v1)
- Multi-grid-operator participant topology (all participants assumed to be under one VNB for v1)
- LEG regulatory reporting exports to ELCOM
- Demand tariff (Leistungstarif) — tracked separately
- Migrating existing vZEV data to LEG type

---

## 3. Actors, permissions, and ZEV scope

All existing permission rules apply unchanged. No new roles are introduced in v1. LEG is a configuration of `ZevType` on an existing `Zev`; all ZEV-scoped permission classes (e.g. `HasZevAccess`) continue to apply.

| Actor | Capability |
|---|---|
| `admin` | Create/edit/delete LEG ZEVs; manage all participants and tariffs |
| `zev_owner` | Edit own LEG ZEV settings; manage participants, tariffs, and invoices |
| `participant` | Read-only access to own invoices, metering data, contract PDF |

---

## 4. Data model

### 4.1 `ZevType` enum (updated)

```python
class ZevType(models.TextChoices):
    ZEV  = "zev",  "Zusammenschluss zum Eigenverbrauch"
    VZEV = "vzev", "Virtueller Zusammenschluss zum Eigenverbrauch"
    LEG  = "leg",  "Lokale Elektrizitätsgemeinschaft"
```

### 4.2 `Zev` model (new fields)

| Field | Type | Constraints | Default | Notes |
|---|---|---|---|---|
| `leg_registration_number` | `CharField(100)` | blank=True | `""` | Official LEG ID issued by ELCOM / VNB; shown on LEG invoices |
| `leg_grid_operator_contract_ref` | `CharField(200)` | blank=True | `""` | Reference number of the grid operator contract |

Both fields are only required when `zev_type == ZevType.LEG` (enforced in serializer `validate()`).

### 4.3 `Participant` model (new field)

| Field | Type | Choices | Default | Notes |
|---|---|---|---|---|
| `participant_role` | `CharField(20)` | `consumer`, `producer`, `prosumer` | `consumer` | For LEG: determines allocation priority; ignored by vZEV engine |

No migration needed on existing participants — default `consumer` is safe.

### 4.4 `MeteringPoint` model (new `meter_type` choice)

```python
class MeterType(models.TextChoices):
    CONSUMPTION  = "consumption",  "Consumption"
    PRODUCTION   = "production",   "Production"
    BIDIRECTIONAL = "bidirectional", "Bidirectional"
    EXCHANGE_POOL = "exchange_pool", "LEG Exchange Pool"  # NEW
```

An `exchange_pool` meter belongs to the LEG (not to any participant). It carries the aggregated internally-traded energy value provided by the grid operator. At most one active `exchange_pool` meter per LEG ZEV is allowed (enforced in `MeteringPoint.clean()`).

### 4.5 `EnergyType` enum (updated, `tariffs/models.py`)

```python
class EnergyType(models.TextChoices):
    LOCAL       = "local",        "Local (Solar / ZEV)"
    GRID        = "grid",         "Grid (Netzstrom)"
    FEED_IN     = "feed_in",      "Feed-in (Einspeisung)"
    LEG_EXCHANGE = "leg_exchange", "LEG Internal Exchange"  # NEW
```

A `Tariff` with `energy_type = leg_exchange` is only valid on a `Zev` with `zev_type == ZevType.LEG` (enforced in `Tariff.clean()`).

### 4.6 `InvoiceItem.ItemType` (updated)

```python
LEG_EXCHANGE_ENERGY = "leg_exchange_energy", "LEG Exchange Energy"
```

---

## 5. LEG billing engine (`backend/invoices/engine_leg.py`)

### Algorithm (per participant, per period)

1. **Identify the exchange pool meter** for the LEG ZEV. If none exists, raise `InvoiceGenerationError`.
2. **Collect participant consumption readings** (IN direction) from assigned `consumption` / `bidirectional` / `prosumer` meters.
3. **Collect exchange pool readings** by timestamp from the `exchange_pool` meter. This is the total kWh available for internal trading in each interval.
4. **Per-interval participant exchange share:**
   - `zev_total_consumption_at_ts` = sum of all participant IN readings at that timestamp
   - `participant_share = participant_kwh / zev_total_consumption_at_ts`
   - `exchanged_kwh = min(participant_kwh, exchange_pool_kwh * participant_share)`
5. **Price exchanged kWh** using the active `LEG_EXCHANGE` energy tariff (HT/NT-aware).
6. **Fixed / fee tariffs** — same logic as vZEV engine (`monthly_fee`, `yearly_fee`, `per_metering_point_*`). These represent the LEG coordination service fee.
7. **Do NOT generate grid energy, feed-in, or local energy line items.** Grid operator handles those directly with each participant.
8. **VAT** applied identically to vZEV if `zev.vat_number` is set.

### Dispatch in `engine.py`

```python
def generate_invoice(zev, participant, period_start, period_end, ...):
    if zev.zev_type == ZevType.LEG:
        from .engine_leg import generate_leg_invoice
        return generate_leg_invoice(zev, participant, period_start, period_end, ...)
    # existing vZEV path unchanged
    ...
```

---

## 6. API changes

### `ZevSerializer`
- Add `leg_registration_number`, `leg_grid_operator_contract_ref` as optional fields.
- `validate()`: if `zev_type == "leg"`, require `leg_registration_number` to be non-empty.

### `ParticipantSerializer`
- Add `participant_role` field (read-write, default `consumer`).

### `MeteringPointSerializer`
- Add `exchange_pool` to the `meter_type` choices.
- `validate()`: reject `exchange_pool` meters on non-LEG ZEVs.

### `TariffSerializer`
- Add `leg_exchange` to valid `energy_type` choices.
- `validate()`: reject `leg_exchange` tariffs on non-LEG ZEVs.

### `InvoiceSerializer`
- No structural changes needed; new `ItemType` value appears naturally in serialized `items`.

---

## 7. Frontend changes

### ZEV settings form
- When `zev_type == "leg"`, show two additional fields: `leg_registration_number`, `leg_grid_operator_contract_ref`.
- Conditionally required validation: `leg_registration_number` required when `zev_type == "leg"`.

### Participant form
- Add `participant_role` dropdown (`consumer` / `producer` / `prosumer`).
- Only show / enforce for LEG ZEVs (hide or lock to `consumer` for vZEV).

### Metering point form
- Add `exchange_pool` to meter type options, visible only when managing a LEG ZEV.

### Invoice detail / line items
- Show `leg_exchange_energy` line items with the label from i18n key `invoice.itemType.legExchangeEnergy`.
- On LEG invoices, suppress the "Local energy" / "Grid energy" / "Feed-in" sections of the invoice summary.

### i18n additions (all 4 locales: `de`, `fr`, `it`, `en`)
- `zev.type.leg`
- `participant.role.consumer` / `participant.role.producer` / `participant.role.prosumer`
- `meterType.exchangePool`
- `invoice.itemType.legExchangeEnergy`
- `tariff.energyType.legExchange`
- `zev.legRegistrationNumber`
- `zev.legGridOperatorContractRef`

---

## 8. PDF template

A LEG invoice PDF should:
- Omit the "Local energy" / "Grid energy" / "Feed-in credit" sections.
- Show a single "Internally exchanged energy (kWh)" line.
- Show the LEG registration number in the header / legal block.
- Retain the service fee section and QR-Rechnung block unchanged.

This is implemented by either:
- A new `PdfTemplate` key `leg_invoice` alongside the existing `invoice`, or
- A conditional block in the existing template checking `zev.zev_type == "leg"`.

Recommendation: use the existing DB-stored template with a conditional block to keep the admin template editor workflow intact.

---

## 9. Migration plan

1. Add `ZevType.LEG` to the enum — non-breaking, no existing data changes.
2. Add `leg_registration_number`, `leg_grid_operator_contract_ref` to `Zev` — nullable/blank, backwards-compatible migration.
3. Add `participant_role` to `Participant` — default `consumer`, backwards-compatible.
4. Add `MeterType.EXCHANGE_POOL` to `MeteringPoint` — non-breaking.
5. Add `EnergyType.LEG_EXCHANGE` to `Tariff` — non-breaking.
6. Add `InvoiceItem.ItemType.LEG_EXCHANGE_ENERGY` — non-breaking.
7. Implement `engine_leg.py` and dispatch in `engine.py`.
8. Update serializers, views, PDF template, frontend.

All existing vZEV and ZEV data is unaffected.

---

## 10. Testing requirements

### Backend (pytest)

- `test_leg_engine.py`:
  - Exchange pool readings → correct participant allocation
  - No exchange pool meter → `InvoiceGenerationError`
  - Zero consumption participant → zero invoice
  - Multiple participants with mixed roles
  - Fee tariffs applied on top of exchange energy
  - VAT applied correctly
  - LEG invoice does not contain grid/feed-in items
- `test_leg_model_validation.py`:
  - `leg_registration_number` required when `zev_type == leg`
  - `exchange_pool` meter rejected on vZEV
  - `leg_exchange` tariff rejected on vZEV
  - At most one `exchange_pool` meter per LEG
- Existing `test_engine.py` / `tests.py` must continue to pass unchanged (vZEV path not touched)

### Frontend (build + manual QA)
- `npm run build` must pass with all new i18n keys present in all 4 locales
- LEG fields hidden on vZEV ZEV settings form
- Participant role field shown only for LEG ZEVs
- LEG invoice line items render correctly

---

## 11. Open questions

1. **Allocation priority rules**: Swiss law may prescribe a specific priority order for distributing the exchange pool (self-consumption first, then alphabetical, then pro-rata). The algorithm in §5 uses simple pro-rata — needs regulatory confirmation.
2. **Exchange pool data source**: Is the VNB always the authoritative source of the aggregated exchange value, or can the LEG compute it from individual meters? This affects whether the `exchange_pool` meter is mandatory.
3. **Multiple VNBs**: Can a single LEG span participants on different grid operators? Deferred to v2.
4. **Producer-only participants**: How is feed-in revenue distributed in an LEG? The current spec omits this. Swiss law may require the LEG to pass feed-in credits through — needs legal review.
5. **Contract PDF**: Does the LEG require a different legal contract template than the vZEV participation contract?
