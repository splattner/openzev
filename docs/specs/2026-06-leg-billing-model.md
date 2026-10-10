# Feature Spec: LEG (Lokale Elektrizitätsgemeinschaft) Billing Model

- Spec ID: SPEC-2026-06-leg-billing-model
- Status: Draft, design review pending (blocked on the SDAT-CH conformance gate and delivery routes of §6.1, tax and contract sign-off of §4.5–§4.6, and the ADR in §1.2)
- Scope: Major
- Type: Feature
- Owners: —
- Created: 2026-06-09
- Updated: 2026-10-11
- Target Release: —
- Related Issues: #515
- Related ADRs: 0001, 0006, 0011, 0013, 0026, 0027, 0028, 0029, 0030; a new ADR is required before implementation (§1.2)
- Impacted Areas: backend | frontend | async jobs | docs

---

## 1. Problem and outcome

LEG is governed by **StromVG 17d–17e / StromVV 19e–19h** (in force 01.01.2026). Members settle internal trading; the VNB determines allocated quantities and bills network + residual components. Members keep their external supply relationships.

| Dimension | vZEV | LEG |
|---|---|---|
| Grid connection | One end-consumer toward VNB; may combine several meters behind the same LV Verknüpfungspunkt | Each member keeps its own connection |
| Billing scope | Local + grid kWh + fees; surplus feed-in credit | Internal purchase (charge) + internal sale (credit) + agreed fees |
| Grid / feed-in | ZEV operator settles with VNB | VNB bills residual, network, metering, external surplus directly (collective invoice per Art. 17e(6) out of scope) |
| Metering source | Participant meters, allocated by OpenZEV (ADR 0013) | VNB-calculated per-member local and residual series, 15-min, SDAT-CH 2025 LEG flows (§4.3) |
| ID | None | SDAT-CH `CommunityID`, assigned by the VNB in a standard format; no ElCom-issued number (§10) |

`backend/invoices/engine.py::generate_invoice()` always allocates readings itself and produces local + grid + feed-in lines. Running it for a LEG would re-allocate what the VNB already allocated and double-bill VNB components.

**Outcome:** traceable consumer charges and producer credits priced from reconciled, VNB-confirmed settlement quantities. No residual, network, or external surplus lines on LEG documents.

### 1.1 Settlement arrangement modelled

StromVG 17d(5) leaves the members' relationship to their own agreement and requires them to appoint a person who represents the community toward the VNB. v1 models the arrangement that VNBs and service providers publish: **central settlement**. The community, through its document issuer, sells LEG electricity to consumers and buys it from producers; it invoices the one and credits the other (BKW, WWZ, RWB, Regio Energie, lokalerstrom; §10). Bilateral settlement, where each producer invoices consumers in its own name, is out of scope.

### 1.2 ADR required

For a LEG, VNB settlement quantities replace `MeterReading` + OpenZEV allocation (ADR 0013) as the billing input, and a participant gets two documents for one period (ADR 0006 assumes one). The first contradicts the rule recorded with ADR 0030 ("`MeterReading` stays the sole billing input", `metering/models.py`). Record both decisions in a new ADR before implementation. §4.5.1 holds the reasoning for the second until then and moves into the ADR.

---

## 2. Scope

### Compatibility promise

- **Supported by design:** any Swiss LEG that uses central settlement (§1.1) and individual VNB billing (`CommunityType CT01`), when OpenZEV receives complete, authorised per-member local and residual quantities in a supported import format.
- **Standard format supported:** SDAT-CH 2025 LEG messages (§4.3) that pass the tested schema and process profile, whichever VNB or data hub sends them. The user guide lists the senders and delivery routes actually verified (§6.1).
- **Other formats:** a VNB CSV or portal export only once its parser profile has a sample, a field mapping and tests. A member's raw smart-meter export is not a settlement file.
- **Unsupported, and detected as such:** collective billing (`CT02`), unknown community, product or document codes, unresolved member points, missing values or periods, missing producer quantities, values cancelled without a replacement, cancellations that do not state their scope (until resolved), conflicting messages with the same creation time, or a delivery route the operator cannot access.

### In scope

| Area | Details |
|---|---|
| `ZevType` | Add `leg` |
| `Zev` | LEG fields `leg_community_id`, `leg_receiver_eic`, `leg_status`, `leg_activation_date`, `leg_tax_confirmed_at`/`_by` (§4.1). VNB = existing `grid_operator`; issuer and representative = existing `ZevPartyRole` roles |
| `Party` | `vat_registration` (`unknown\|not_registered\|registered`) + `vat_registration_since`, read by producer credits (§4.6) |
| Members | Existing `Participant` + `MeteringPoint` + `MeteringPointAssignment`; add `MeteringPointAssignment.tariff_group` (§4.2) |
| Settlement data | SDAT-CH 2025 LEG parser; new `metering.LegSourceMessage` + `LegSourceValue` (as delivered) and `LegSettlementBatch` + `LegSettlementQuantity` (assembled, approved); preview/generate predicates; supersede rules (§4.3) |
| Tariffs | `EnergyType.leg_purchase` + `leg_sale`; `Tariff.tariff_group`; flat CHF/kWh energy prices; fixed fees scoped by group (§4.4) |
| Documents | `Invoice.document_kind` (`invoice` \| `producer_credit`), `Invoice.replaces`, `Invoice.approved_at`; `InvoiceItem.ItemType` `leg_purchase_energy` + `leg_sale_energy`; `InvoiceLegSettlementEvidence`; `LegExternalSettlement` (§4.5) |
| Engine | `invoices/engine_leg.py`; dispatch inside `generate_invoice` / `generate_invoices_for_zev` (§6.2) |
| Billing cockpit | LEG branch in readiness, attention, period overview (§6.4) |
| API / frontend / PDF / email | §5, §6.3, §7 |
| Transfer / backups / purge | Archive format 8; backups registry; purge removes settlement files (§6.4) |
| Migrations | Schema migrations for every field and table above. Existing rows get `document_kind="invoice"` and blank `tariff_group`; ZEV/vZEV behaviour is unchanged |

### Out of scope for v1

- ZEV/vZEV as LEG member (possible per BKW/WWZ; needs a parent–child model → explicit rejection)
- Bilateral settlement (producers invoicing in their own name, §1.1)
- VAT on producer credits (VAT-registered producers); Doc B carries no VAT (§4.6)
- Netting/offset of Doc A against Doc B; executing producer payouts (no producer IBAN on record)
- Fee recipients other than the issuer; per-kWh service fees; stacking several energy tariffs per series
- Reversal/adjustment documents. Approved or sent documents are corrected by cancel + regenerate, keeping the issued original (§4.5.2); **paid documents cannot be corrected in v1** (ADR 0006 forbids cancelling them), so a difference is settled outside OpenZEV and only recorded in it (§4.5.2). Correcting paid invoices and keeping cancelled ones for all ZEV types is #388
- Full dated VAT history per producer. v1 holds the current status and the date since which it applies, and refuses periods before that date (§4.6)
- Multi-VNB / cross-area LEG (same area + level + municipality + ≤36 kV assumed)
- VNB collective invoice (Art. 17e(6)); network/discount calculation (VNB-owned, 20%/40%). No `vnb_billing_mode` field until that feature exists
- Automated SDAT transport (hub download, FTPES). v1 is manual upload; the manager uploads the plausibilised monthly delivery and any replacements. Taking in the daily information stream automatically would store each interval up to six times and comes with the transport
- Period-total quantities from non-standard exports. A future parser profile that needs them must add an aggregate representation together with its boundary rules (one assignment row, one tariff and one invoice period per row)
- Internal allocation keys other than the VNB's. BD LEG §7.1(3) lets a LEG agree its own key; v1 bills the VNB's local shares
- Dynamic / HT/NT LEG prices; ELCOM exports; Leistungstarif
- vZEV→LEG migration; moving a metering point between ZEVs (`meter_id` is unique across ZEVs)
- Reports built on OpenZEV's own allocation or on local/grid lines, for LEG ZEVs: annual report, annual statement, financial summary, the energy-balance analytics. They answer `leg_report_unsupported` and are hidden (§6.4)
- Writing LEG series into `MeterReading`. Measured raw data, where the VNB delivers it, still imports through the existing SDAT-CH importer for charts; it is never LEG billing input

---

## 3. Actors, permissions, and ZEV scope

No new roles. Platform roles are `admin|user`; what an account may do in a ZEV comes from `zev.access` (grants, managing party roles, participant links; ADR 0027, ADR 0028 decision 8).

| Actor | Capability |
|---|---|
| `admin` | Everything below in every ZEV, including disabled ones |
| manager (grant `manager`, or an account of the party holding `issuer` or `representative`) | Write LEG settings, assignments, tariffs, batches (upload, reconcile, approve, delete), tax confirmation; generate and run the invoice workflow. Writes on a disabled ZEV are rejected (as `InvoiceViewSet.generate` does today) |
| viewer (grant `viewer`) | Read everything a manager reads, including batch preview and findings; no writes |
| participant link | Own documents once sent (`sent_to_participant()`); own settlement quantities inside own assignment windows, from approved non-superseded batches only. No batch, finding or config read |
| no relation | Nothing; objects of other ZEVs are `404` through `ZevScopedQuerySetMixin`, without disclosing existence |

Per-action permissions are spelled out in §5. Every LEG `400` carries a stable `code` (§5).

---

## 4. Data model

Code grounding: `ZevType zev|vzev` (`zev/models.py`); `Zev.grid_operator` + `grid_operator_elcom_id`; `ZevPartyRole` roles `issuer|representative|landowner`, read through `zev.parties.issuer_on` / `representative_on`; `MeteringPoint.meter_id` unique across all ZEVs; `MeteringPointAssignment` with inclusive `valid_from`/`valid_to`, no overlapping windows per metering point (`_validate_no_overlap`, on `clean()` and `save()`), `allocation_mode personal|community`; `MeterReading` unique on `(metering_point, timestamp, direction)`; `EnergyType local|grid|feed_in` and `BillingMode` `energy`, `percentage_of_energy`, `monthly_fee`, `yearly_fee`, `per_metering_point_monthly_fee`, `per_metering_point_yearly_fee`, `shared_monthly_fee`, `shared_yearly_fee` (`tariffs/models.py`); `InvoiceItem.ItemType local_energy|grid_energy|feed_in|fee|credit`; `Invoice` one live row per participant and overlapping period, `issuer`/`recipient` JSON frozen from approval on (`invoices/document_parties.py`); `generate_invoice(participant, period_start, period_end, generation_context=None)` raising `ValueError`; VAT from `Zev.vat_mode` + `VatRate` on `period_end`, applied to the subtotal after credits. Civil dates are inclusive at both ends (ADR 0001, ADR 0026); only UTC datetimes are half-open (`allocation.validity.period_window`).

### 4.1 `Zev` — LEG configuration

**Model:** `zev.models.Zev`.

```python
class ZevType(models.TextChoices):
    ZEV = "zev", "ZEV (Zusammenschluss zum Eigenverbrauch)"
    VZEV = "vzev", "vZEV (Virtueller Zusammenschluss zum Eigenverbrauch)"
    LEG = "leg", "LEG (Lokale Elektrizitätsgemeinschaft)"  # NEW
```

Reused, not added:

| Need | Existing |
|---|---|
| VNB (one in v1) | `grid_operator` (+ `grid_operator_elcom_id` when picked from the ElCom list) |
| Document issuer, QR creditor | `ZevPartyRole` `issuer` + `Zev.bank_iban` (IBAN stays on the ZEV, ADR 0028 decision 6) |
| Representative toward the VNB (StromVG 17d(5)) | `ZevPartyRole` `representative`; may be the same party as the issuer |
| Community VAT | `vat_mode`, `vat_number` |

New fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `leg_community_id` | `CharField(13)`, blank | `""` | The VNB-assigned SDAT-CH `CommunityID`: six characters of the VSE network identifier, `-`, six characters `0-9A-Z` (validated). Required before the first import, and every message must carry it (§4.3). Printed on both documents. Taken from the VNB's confirmation or a message, never derived from `grid_operator_elcom_id`. Locked once messages exist |
| `leg_status` | `CharField(20)` | `"draft"` | `draft\|submitted\|active\|ended`; community state as reported by the VNB, maintained by the manager. Distinct from batch `review_state` (§4.3) |
| `leg_activation_date` | `DateField`, null | `NULL` | VNB-confirmed activation |
| `leg_receiver_eic` | `CharField(16)`, blank | `""` | EIC-X of the market actor the VNB addresses this LEG's data to (receiver role `CEM`): the representative's own code, or that of a mandated service provider, which then enters the same code in every LEG it serves. 16 characters when set. When set, every message's receiver must match (§4.3). An EIC-X identifies a market actor, never a member or a metering point. An instance-wide receiver configuration comes with automated transport |
| `leg_tax_confirmed_at` | `DateTimeField`, null | `NULL` | Set only by the tax-confirmation action (§4.6) |
| `leg_tax_confirmed_by` | FK → `User`, `SET_NULL`, null | `NULL` | Who confirmed |

Rules:

- On a non-LEG ZEV every `leg_*` field keeps its default (`ZevSerializer` → `400 leg_fields_on_non_leg`).
- `Zev.clean()` and `ZevSerializer.validate`: `grid_operator` required once `leg_status != "draft"`; `leg_activation_date` required for `active` and `ended`.
- `zev_type` cannot change to or from `leg` once the ZEV has a tariff, an assignment, an invoice or a settlement batch (`leg_zev_type_locked`). `ZevSerializer` (`fields = "__all__"`) must constrain it.
- `leg_tax_confirmed_at`/`_by` are read-only in `ZevSerializer`.
- Buildings: a LEG is multi-site like a vZEV. `zev.buildings.assign_buildings_from_participants` currently sends every non-vZEV to one building (`if zev.zev_type != ZevType.VZEV`); change the test to `zev_type == ZevType.ZEV`.
- Not added: `vnb` (duplicate of `grid_operator`), `vnb_billing_mode` (it could hold only one value until the collective mode exists), a mandatory ElCom-issued LEG number, a second contract-reference field.

### 4.2 Members, metering points and assignments

A LEG member is a `Participant`. Each of its VNB metering points is a `MeteringPoint` of the LEG ZEV, and holding a point over time is a `MeteringPointAssignment` (assignment windows are the single source of truth for who holds a point, ADR 0001).

What this gives without new code: one identity graph; the metering-points page, buildings, transfer, per-metering-point fees and windowed participant visibility work for a LEG; `meter_id` uniqueness means a point belongs to one community on this instance; a member may hold several points at once (household + PV meter).

The VNB point ID in the file (`VSENationalID`) is `MeteringPoint.meter_id`. In SDAT-CH, a member who both consumes and produces has two metering points, one per flow (§4.3). `MeteringPoint.meter_type` (`consumption|production|bidirectional`) must not contradict the flow the VNB sends for a point (`leg_flow_mismatch`); within that, the quantities decide position. Entry/exit dates are the assignment's `valid_from`/`valid_to` (inclusive).

New field:

| Field | Type | Default | Notes |
|---|---|---|---|
| `MeteringPointAssignment.tariff_group` | `CharField(100)`, blank | `""` | Selects the holder's LEG prices and group-scoped fees for the window (§4.4). Must be blank on non-LEG ZEVs. It sits on the assignment for the same reason `allocation_mode` does: it is a billing attribute of holding the point for a window, so a price-group change is a new window |

LEG rules (assignment serializer + `MeteringPointAssignment.clean()`):

- `allocation_mode` must be `personal` (`leg_community_allocation`). Community meters are a ZEV concept; in a LEG the VNB allocates.
- `valid_from`/`valid_to` are the VNB-confirmed entry/exit dates, not the date a member registered or consented in a VNB portal. A window that starts after today shows as "pending activation". There is no separate confirmation flag.
- The existing no-overlap rule per metering point applies. There is no per-participant overlap rule.
- `has_behind_meter_generation` and supplementary sources stay available as statistics (ADR 0030).

### 4.3 Settlement data (new)

The import contract is the **SDAT-CH 2025 LEG exchange** (§10). The VNB sends the LEG representative, or the service provider it mandates, the per-member flows of the process "Messdatenaustausch LGZ/EGZ an LEG-Vertreter" (SDAT-CH Messdatenaustauschprozesse 2025 V2 §1.12), and optionally the community aggregates of §1.13. No VNB-specific rule lives in the model or the billing engine. A VNB whose deliveries deviate from the standard gets a named parser profile, backed by its own sample and conformance tests (§6.1).

```text
delivery            v1: manual upload of .xml / .xml.gz files, several at once; later: hub download
  → parser profile  v1: sdat_ch_2025_leg; others only with a sample, a field mapping and tests
  → LegSourceMessage + LegSourceValue    per message; per point, flow, product and interval
  → assemble        newest Creation wins per (point, flow, product, interval) → LegSettlementBatch
  → reconcile → approve
  → LEG pricing and documents (§4.4–§4.5), unchanged
```

**Models:** `metering.models.LegSourceMessage`, `LegSourceValue`, `LegSettlementBatch`, `LegSettlementQuantity`. They hold VNB-calculated allocations, not measurements, so they are distinct from `MeterReading`.

#### What the standard delivers

Per member metering point, the VNB sends three products for the point's flow, at 15-minute resolution. §1.12 counts "drei Datenflüsse pro Marktakteur"; a member who both consumes and produces has six flows over two metering points.

| SDAT-CH information | Metering point element | Product code | OpenZEV `series` |
|---|---|---|---|
| LGZ-LEGE (LEG energy consumed) | `ConsumptionMeteringPoint` | `2404050010123` Local active energy | `leg_purchase` (priced) |
| EGZ-LEGE (LEG energy fed in) | `ProductionMeteringPoint` | `2404050010123` Local active energy | `leg_sale` (priced) |
| LGZ-LEGR / EGZ-LEGR (residual) | either | `2404050010124` Residual active energy | `reconcile_only` |
| LGZ-LEGT / EGZ-LEGT (total measured) | either | `8716867000030` Energy active | `reconcile_only` |

The header carries: `ValidatedMeteredData` (`DocumentType E66`, sender role `MDR`) for member flows, or `AggregatedMeteredData` (`E31`, sender role `DEA`) for the community sums; receiver role `CEM` (Community Energy Manager); `BusinessReason C40` (metered data for community management); a `Community` with `CommunityID` and `CommunityType`; `DocumentFunction` `9` original, `5` replace or `1` cancellation. Each observation has `Position`, `Volume` and an optional `Condition` (`21` temporary, `56` estimated). A missing `Condition` means only that the observation carries no quality flag. The standard keeps measurement status apart from the VNB's plausibility check, so the absence of a flag is not proof that a value is final.

Rules of the standard the import relies on (SDAT-CH Hauptdokument 2025 §4.8–§4.11; Messdatenaustauschprozesse 2025 V2 §1.1–§1.2, §1.12–§1.13):

- Intervals are positions counted from `StartDateTime` at the stated resolution: 96 per day, **92 or 100 on DST change days**. Only complete days or months are sent. The parser derives each interval from its `Position` and refuses a count that does not fit the interval (`leg_position_mismatch`). The existing `sdatch_importer` does not follow these rules (#956), so only its XML hardening and `_parse_ts` are reused. The LEG parser shares none of its persistence policy.
- Corrections arrive as new messages (new `DocumentID`) with function `replace`, and **the version with the newest `Creation` timestamp applies**. They can arrive until the 3-month clearing deadline.
- Plausibilised data arrive by the end of the 5th working day after the delivery month. Earlier deliveries of the same flow (daily, the last five days each time) are unplausibilised and meant for information. Both use `C40`, and no message carries a "final" flag.
- A large delivery is split into several files by metering point, and each file is an independent message.
- A missing value is never zero ("0-Werte sind kein Ersatz für fehlende Werte").
- `CommunityID` is assigned by the VNB: the first six characters of its VSE network identifier, a hyphen, and six characters `0-9A-Z`. It is unique and permanent, also after the community dissolves. `CommunityType CT01` "Basis LEG" (the community or its representative bills members only the local share) is the v1 model; `CT02` "Zusammenfassende Rechnung LEG" (collective billing, Art. 17e(6)) is refused.

#### `LegSourceMessage`

| Field | Type | Notes |
|---|---|---|
| `zev` | FK → `Zev`, `CASCADE` | Must be a LEG |
| `source_file` | `FileField(upload_to="leg_settlement/")` | Bytes as received (`.xml` or `.xml.gz`) |
| `source_filename` | `CharField(256)` | |
| `checksum` | `CharField(64)` | SHA-256 of the received bytes |
| `parser_profile` | `CharField(40)` | `sdat_ch_2025_leg` in v1 |
| `document_id` | `CharField(35)` | `InstanceDocument/DocumentID` |
| `document_type` | `CharField(3)` | `E66` member flows, `E31` community aggregates |
| `document_function` | `CharField(1)` | `9` original, `5` replace, `1` cancellation |
| `source_created_at` | `DateTimeField` | `InstanceDocument/Creation`; decides which version applies |
| `sender_eic` / `receiver_eic` | `CharField(16)` | Header parties; the receiver role must be `CEM` |
| `business_reason` | `CharField(3)` | Must be `C40` |
| `community_id` | `CharField(13)` | Must equal `Zev.leg_community_id` |
| `community_type` | `CharField(4)` | Must be `CT01` |
| `report_start` / `report_end` | `DateTimeField` (UTC) | `ReportPeriod` |
| `received_at` / `received_by` | `DateTimeField` / FK → `User` `SET_NULL`, null | |

`UniqueConstraint(zev, sender_eic, document_id)`. Uploading the same message again (same IDs, same checksum) is acknowledged without a second row; the same IDs with different bytes → `leg_document_id_conflict`. Filenames and checksums are not identity.

#### `LegSourceValue`

| Field | Type | Notes |
|---|---|---|
| `message` | FK → `LegSourceMessage`, `CASCADE` | |
| `metering_point` | FK → `MeteringPoint`, `RESTRICT`, null | Resolved from `VSENationalID` within the ZEV. Null only for `E31` community aggregates |
| `source_point_id` | `CharField(100)`, blank | `VSENationalID` as in the file; blank for aggregates |
| `flow` | `CharField(11)` | `consumption\|production`, from the metering point element (`E66`) or `FlowCharacteristic` `E17`/`E18` (`E31`) |
| `product` | `CharField(13)` | `2404050010123\|2404050010124\|8716867000030`; any other → `leg_unknown_product` |
| `interval_start` / `interval_end` | `DateTimeField` (UTC) | `Interval` start + (`Position` − 1) × resolution; half-open |
| `is_cancellation` | `BooleanField`, default `False` | `True` for a key explicitly listed by a cancellation message: this row is a tombstone, not a delivered value |
| `quantity_kwh` | `Decimal(14,4)`, null | Normalised for value rows; `NULL` for tombstones. `source_quantity_text` and `source_unit` kept beside it, blank for tombstones |
| `condition` | `CharField(2)`, blank | `""` no quality flag, `21` temporary, `56` estimated. An unflagged value is eligible subject to the other checks; the parser never claims it is final |

`UniqueConstraint(message, source_point_id, flow, product, interval_start)`; `CheckConstraint((is_cancellation = True AND quantity_kwh IS NULL) OR (is_cancellation = False AND quantity_kwh IS NOT NULL AND quantity_kwh >= 0))`; `CheckConstraint(interval_end > interval_start)`. Tombstones keep the same point, flow, product and interval key as values, with `condition = ""`; import permits them only when `message.document_function == "1"`.

Import (`metering/importers/leg_sdat.py`, one transaction per file). Any error below stores nothing for that file and answers `400` with its findings:

1. Hardening: `lxml` with entities, DTD and network off; at most one gzip layer; compressed size ≤ `MAX_UPLOAD_BYTES` (50 MB, the standard's own limit) and a cap on the decompressed size. Malformed gzip/XML, schema-invalid content or a hardening-limit violation → `leg_parse_error`; the specific semantic codes below take precedence for their conditions.
2. Header: known root and `DocumentType`, `C40` and receiver role `CEM` (`leg_wrong_process` otherwise; for example a supplier's residual flow with `E88`); `CommunityType CT01` (`leg_community_type_unsupported`); `CommunityID == Zev.leg_community_id` (`leg_community_mismatch`, or `leg_community_id_missing` while the field is empty); receiver EIC equal to `Zev.leg_receiver_eic` when that is set (`leg_receiver_mismatch`).
3. Values: an unknown `VSENationalID` → `leg_unmapped_point` naming it (a point of another ZEV reads the same); a flow contradicting a consumption-only or production-only point → `leg_flow_mismatch`; values outside every assignment window of the point → `leg_outside_assignment`; positions not matching interval and resolution → `leg_position_mismatch`.
4. A `cancellation` message is always stored. Only what the message itself states becomes data:
   - **Keys it lists** (point, flow, product and positions) are stored as `LegSourceValue` rows with `is_cancellation=True` and `quantity_kwh=NULL`: tombstones for exactly those keys (assembly, below), with the message as their provenance. No quantity is invented even if the cancellation includes a volume.
   - **A cancellation that lists no keys** produces no tombstones; OpenZEV does not invent its scope. Every batch whose period overlaps the message's `ReportPeriod` (for the points it names, or for the whole community if it names none) gets the blocking finding `leg_cancellation_unresolved`, assembled and approved batches alike, so generation for those periods stops. Blocking broadly is deliberate; recording a guessed scope as if the VNB had supplied it is not allowed.
   - Such a cancellation is resolved either by a parser profile that interprets it from the applicable 2025 XSD and examples, or by a manager's **resolution backed by external evidence** (`LegCancellationResolution`, below). Without evidence it stays blocking. A later replacement covering the keys supersedes either outcome.

**Messages are append-only.** There is no delete endpoint. Every stored message has passed the community, type, process and receiver checks, so it is VNB data for this LEG. Deleting one could hide a later correction or a cancellation, even one that no batch references yet. Only a ZEV purge removes messages.

#### `LegCancellationResolution` (append-only)

A manager's decision on a cancellation that lists no keys. The rule that a decision needs external evidence is an OpenZEV safety rule; SDAT-CH does not define this step.

| Field | Type | Notes |
|---|---|---|
| `message` | FK → `LegSourceMessage`, `CASCADE` | Must be a cancellation without listed keys |
| `outcome` | `CharField(10)` | `keys`: the listed keys are cancelled and become tombstones marked `manually_resolved`. `no_effect`: the cancellation does not affect this LEG's data |
| `keys` | `JSONField` | `[{point, flow, product, interval_start, interval_end}]`; required for `keys`, empty for `no_effect` |
| `evidence_reference` | `CharField(200)`, required | The VNB's confirmation that identifies the cancelled document and states its scope (for `no_effect`: why it does not affect this LEG), e.g. a case number or the dated message from the VNB |
| `evidence_file` | `FileField(upload_to="leg_settlement/evidence/")`, blank | Copy of that confirmation, when available |
| `reason` | `TextField`, required | The manager's explanation |
| `supersedes` | `OneToOneField` → self, `RESTRICT`, null (`related_name="superseded_by"`) | The earlier resolution this one replaces |
| `resolved_by` / `resolved_at` | FK → `User` `SET_NULL`, null / `DateTimeField(auto_now_add)` | |

Rules:

- A free-text reason alone never resolves a cancellation. If the VNB cannot confirm the scope, the cancellation stays blocking.
- Resolutions are never edited or deleted. A wrong or outdated decision is corrected by a new resolution whose `supersedes` names the current one (`409 leg_resolution_not_current` if it names any other, which also guards against two managers resolving at once). The original stays on record with its evidence. The current resolution is the one nobody supersedes.
- Each new resolution re-runs the later-change check (§4.3, "A later change blocks billing") for every batch the cancellation's `ReportPeriod` overlaps. Where the selected data changes, `leg_newer_source_data` blocks those batches and generation until a new revision is approved.
- Every resolution is audited (`leg_cancellation_resolution.create`, with outcome, keys, evidence reference and the superseded resolution).

#### `LegSettlementBatch`: an assembled, approvable snapshot

A batch is created by **assembling** a period from the stored messages, never by an upload. Entries are `LegSourceValue` rows (values and tombstones), plus the keys of each cancellation's current `LegCancellationResolution` with outcome `keys`; those manual tombstones use the cancellation message's `source_created_at` and retain the resolution as evidence, without adding or changing source rows. For every key `(metering point or community, flow, product, interval)` inside the period, the entries of all messages are ordered by `source_created_at` and the newest decides:

- a value (`is_cancellation=False`) → copied into a `LegSettlementQuantity`, whose `source_value` records which message's value won (so a bill assembled from several files stays explainable value by value); tombstone rows never become quantities;
- a tombstone (the newest entry is a cancellation) → no quantity; the key is a gap, reported as `leg_cancelled_values` and caught by completeness. A later original or replacement for the key supersedes the tombstone;
- **a tie**: two messages with the same `Creation` that disagree on the key (different value or condition, or a value against a tombstone) → `leg_ambiguous_source`, blocking. Upload order never decides. Identical entries are not a tie.

Batches and quantities are immutable.

| Field | Type | Default | Notes |
|---|---|---|---|
| `zev` | FK → `Zev`, `CASCADE` | — | |
| `period_start` / `period_end` | `DateField` | — | **Inclusive** civil dates (e.g. 2026-01-01 … 2026-01-31) |
| `revision` | `PositiveIntegerField` | `1` | `max + 1` among batches with the same `(zev, period_start, period_end)`; display only |
| `review_state` | `CharField(20)` | `"assembled"` | `assembled\|reconciled\|approved\|superseded` |
| `assembled_at` / `assembled_by` | `DateTimeField` / FK → `User` `SET_NULL`, null | — | |
| `latest_source_created_at` | `DateTimeField` | — | Newest `Creation` among contributing messages; display only. Later changes are found by re-running the assembly rule (below), not by comparing this timestamp |
| `findings` | `JSONField` | `[]` | `{code, message, kind, meter_id?, interval_start?}`; `kind` is `blocking`, `overridable` or `informational` |
| `reconciled_at` | `DateTimeField`, null | — | |
| `approved_at` / `approved_by` | `DateTimeField` / FK → `User` `SET_NULL`, null | — | |
| `override_reason` | `TextField`, blank | `""` | Required to approve over overridable findings |
| `override_reference` | `CharField(200)`, blank | `""` | Ticket reference for the override |
| `superseded_by` | FK → self, `RESTRICT`, null | — | Set when a later approval replaces this batch |

Constraints: `CheckConstraint(period_end >= period_start)`; `UniqueConstraint(zev, period_start, period_end, condition=Q(review_state="approved"))` as a backstop for identical periods. Overlap between different periods is enforced by the approval service (below).

`LegSettlementQuantity`: `batch` FK `CASCADE`; `source_value` FK → `LegSourceValue`, `RESTRICT` (provenance); copies of `metering_point` (`RESTRICT`, null for community rows), `flow`, `product`, `series` (derived per the table above), `interval_start`/`interval_end`, `quantity_kwh` and `condition`. `CheckConstraint(metering_point IS NOT NULL OR series = 'reconcile_only')`; index on `(batch, metering_point, series)`. `RESTRICT`, not `PROTECT`, so a ZEV purge (which cascades both sides) still works. Community rows feed reconciliation only; they never go through assignment lookup, pricing, completeness or participant visibility.

The holder is **not stored**. Generation resolves it per interval through `AssignmentWindows.assignment_at(point, interval_start)`, so an assignment corrected after assembly is honoured, and a value that has fallen into a gap blocks generation (`leg_unmapped_point`). With 15-minute values, every price, group, holder or period boundary falls on an interval edge, so no granularity rule is needed in v1.

Predicates (never inferred from enum order):

- `may_preview(batch) := review_state in {reconciled, approved}`.
- `may_generate(zev, period_start, period_end) :=` all of:
  1. LEG setup complete for the period (§4.6);
  2. the approved batches overlapping the period cover every civil day of it (a `superseded` batch never counts); otherwise `leg_period_not_covered`;
  3. **series completeness against today's assignments**: every point assigned during the period has complete values (below) for its effective window in those batches. Re-checked at generation, so an assignment added or extended after approval blocks with `leg_incomplete_series` instead of billing low;
  4. **no unprocessed later change**: re-running the assembly rule over today's messages yields exactly the quantities of each of those approved batches (no changed value or condition, no new tombstone, no tie). Otherwise `leg_newer_source_data`, blocking;
  5. no LEG document overlapping the period is stale and unresolved (§4.5.2, `leg_stale_documents`).

  Batch date coverage alone never satisfies 3.

Reconcile (`reconcile_batch`). Findings are blocking, overridable (approval needs an override reason) or informational:

| Check | Finding | Kind |
|---|---|---|
| Completeness: every point assigned during the period has all three products of its flow for every interval of its effective window. A missing value is a gap, never zero; a point absent from the messages is the same finding | `leg_incomplete_series` (point, product, first missing interval) | blocking |
| Per point and interval: total = residual + local | `leg_point_balance` | blocking |
| Community, per interval and over the period: Σ local consumption = Σ local production | `leg_community_balance` | blocking |
| Community aggregates (`E31`), when delivered, equal the sums of the member values per flow, product and interval | `leg_aggregate_mismatch` | blocking |
| Local consumption without any local production in the period, or the reverse | `leg_missing_seller_data` | blocking |
| A key's newest entry is a tombstone (listed by the cancellation, or by a manager's resolution) | `leg_cancelled_values` (keys listed, with provenance) | blocking |
| A cancellation without listed keys overlaps the period and is unresolved | `leg_cancellation_unresolved` | blocking |
| Two messages with the same `Creation` disagree on a key | `leg_ambiguous_source` | blocking |
| A member value has `Condition 21` (temporary) | `leg_temporary_values` | overridable |
| Early-approval warning: assembled before the date by which the standard expects plausibilised data | `leg_before_plausibilisation` | overridable |
| Values with `Condition 56` (estimated: substitute values the VNB also bills with) | `leg_estimated_values` | informational |
| Corrections remain possible until the clearing deadline | `leg_corrections_possible_until` | informational |

Balance checks use strict decimal equality after normalisation until real deliveries show the VNBs' rounding; any tolerance is then recorded per parser profile with its evidence. Never plug gaps.

The `leg_before_plausibilisation` date is a **heuristic threshold, not evidence** that a delivery was checked. It is the end of the 5th weekday (Monday to Friday, `Europe/Zurich`) after the period's last month, plus two calendar days as a margin for public holidays, which the heuristic does not model. It only warns against early approval. Passing the date never changes a batch's state or findings by itself; the data's state comes from its quality codes and from later corrections.

State machine: `assembled → reconciled` (reconcile service, only without blocking findings; may be re-run while `assembled`) `→ approved` (approval service) `→ superseded` (a later approval covers it). No other transitions. A batch may be deleted only while `assembled` or `reconciled`.

Approval (`metering/leg_services.py::approve_batch`, one transaction):

1. `select_for_update()` the `Zev` row, so all approvals of one community run one at a time.
2. Re-check: `review_state == reconciled` (`leg_unreconciled` otherwise); `leg_status in {active, ended}`; `period_start >= leg_activation_date`; a non-empty `override_reason` when any overridable finding exists (`leg_override_required`); re-running the assembly rule over today's messages yields the batch's quantities unchanged (`leg_newer_source_data` otherwise).
3. Collect approved batches overlapping the new period. Each must lie entirely inside the new period, else `leg_partial_supersede`: a correction must cover every day of what it replaces.
4. Set them `superseded` with `superseded_by = new` **before** approving the new batch. Django cannot defer a conditional `UniqueConstraint`, so this order matters.
5. Set the new batch `approved`, stamp `approved_at`/`approved_by`, write the audit event (findings overridden, override reason and superseded IDs in metadata). There is no silent auto-finalisation.

Approval certifies quantities, not prices: it does not look at tariffs, issuer, VAT status or invoices. Documents priced from a now-superseded batch become stale and follow §4.5.2.

**A later change blocks billing; it is never applied silently.** After each import, the assembly rule is re-run for every assembled, reconciled or approved batch the new message overlaps:

- **Changed** (a different value or condition, a new tombstone, or a tie) → `leg_newer_source_data`, **blocking**. An assembled or reconciled batch can no longer be approved, and generation for the approved batch's period is refused (`may_generate` 4). Readiness lists the already issued documents of that period as affected. They become stale, and follow §4.5.2, once the new revision is approved.
- **Unchanged** (the later message repeats the selected values) → `leg_newer_source_unchanged`, informational.

The manager resolves a change by assembling a new revision, reconciling it and approving it, which supersedes the old batch. Approved batches stay immutable: the change is computed from the stored messages and is not written into the approved batch.

### 4.4 `EnergyType`, `Tariff`, price groups and fees

**Model:** `tariffs.models`. Add `EnergyType.LEG_PURCHASE = "leg_purchase"` (charge) and `EnergyType.LEG_SALE = "leg_sale"` (credit). Add `Tariff.tariff_group: CharField(100), blank, default ""`.

On a LEG ZEV (tariff serializer + `Tariff.clean()`):

- `energy` tariffs must use `leg_purchase` or `leg_sale`. `local|grid|feed_in`, `percentage_of_energy` and `dynamic_source` are rejected (`leg_tariff_type`). Exactly one `flat` `TariffPeriod`.
- Fixed fees: `monthly_fee` and `yearly_fee` in any group; `per_metering_point_*` and `shared_*` only with a blank group.
- VSE tariff import and dynamic sources are unavailable: they price VNB components.

On a non-LEG ZEV, `leg_*` energy types are rejected and `tariff_group` must be blank.

Price resolution (`engine_leg`): for energy type E, the holder's assignment group G and civil day D, candidates are the `energy` tariffs with `energy_type == E`, `tariff_group == G` (blank matches blank only) and `valid_from <= D <= valid_to` (or no `valid_to`), the same inclusive test as `_tariff_is_active`. Exactly one must match: zero → `leg_no_tariff`, several → `leg_ambiguous_tariff`. Preview shows them as blockers and generation fails with them; batch approval ignores them, because it certifies quantities, not prices (§4.3). Unlike vZEV, where every active tariff of an energy type is charged (`_price_energy`), v1 does not stack tariffs.

Fees are always on Doc A (§4.5). A fee tariff with a blank group applies to every member, as on a vZEV. A fee with group G applies to a participant in each month in which one of their LEG assignments with group G is active. Fees are computed by the existing `_price_fixed_fees` over the filtered tariff list, so month counting, yearly twelfths and shared denominators (`_count_active_participants_by_month`, `split_key`) are unchanged. Every Doc A line is owed to the issuer, who is the single QR creditor, so there is no fee-recipient field.

### 4.5 `Invoice` + `InvoiceItem` — two documents per member and period

New `Invoice` fields:

| Field | Type | Default | Notes |
|---|---|---|---|
| `document_kind` | `CharField(20)` | `"invoice"` | `invoice` ("Invoice") \| `producer_credit` ("Producer credit note"). Existing rows: `invoice`. Non-LEG ZEVs only ever have `invoice` |
| `total_leg_purchase_kwh` | `Decimal(12,4)` | `0` | Doc A |
| `total_leg_sale_kwh` | `Decimal(12,4)` | `0` | Doc B |
| `replaces` | FK → self, `SET_NULL`, null (`related_name="replaced_by"`) | `NULL` | The cancelled, approved document this one corrects (§4.5.2) |
| `approved_at` | `DateTimeField`, null | `NULL` | Set by `invoices.workflow.approve_invoice` for every ZEV type: the moment the document became final (its issuer/recipient copy freezes then). No backfill; no LEG document predates the migration. LEG regeneration keys retention on it (§4.5.2) |

`InvoiceItem.ItemType` adds `LEG_PURCHASE_ENERGY = "leg_purchase_energy"` and `LEG_SALE_ENERGY = "leg_sale_energy"` (both fit the existing `max_length=20`).

New `invoices.models.InvoiceLegSettlementEvidence`, shaped after `InvoiceDynamicSourceEvidence`: `invoice` FK `CASCADE` (`related_name="leg_evidence"`), `batch` FK `RESTRICT`, `batch_revision` `PositiveIntegerField`, `overridden` `BooleanField` (the batch was approved over overridable findings). `UniqueConstraint(invoice, batch)`. Written in the same transaction as the document.

New `invoices.models.LegExternalSettlement`, the record that a paid stale document's difference was settled outside OpenZEV (§4.5.2):

| Field | Type | Notes |
|---|---|---|
| `invoice` | `OneToOneField` → `Invoice`, `CASCADE` (`related_name="leg_external_settlement"`) | Must be a LEG document, `paid` and stale when recorded (`leg_settlement_not_applicable` otherwise) |
| `amount_chf` | `Decimal(10,2)` | The difference settled, signed from the member's point of view (positive = the member paid more). The UI suggests it from the preview of the period under the new batch; the manager enters the actual amount |
| `reference` | `CharField(200)` | External settlement reference (bank transfer, credit note number), required |
| `note` | `TextField`, blank | |
| `recorded_by` / `recorded_at` | FK → `User` `SET_NULL`, null / `DateTimeField(auto_now_add)` | |

Immutable once recorded in v1: no update or delete endpoint.

**Identity.** One live document per `(participant, overlapping period, document_kind)`. `_discard_replaceable_invoices` and `locked_overlapping_invoices` gain a `document_kind` parameter (default `invoice`) and filter on it; for ZEV/vZEV every row is `invoice`, so their behaviour is unchanged. The two documents of one prosumer are found by `(zev, participant, period_start, period_end)`.

**Roles per kind.** `Invoice.issuer` always means the document's author and `Invoice.recipient` its addressee; which of them supplies the electricity depends on `document_kind`. The PDF, the frontend and MCP `explain_invoice` read roles from this table and never assume "issuer = supplier":

| Role | Doc A (`invoice`) | Doc B (`producer_credit`) |
|---|---|---|
| Document author (`issuer` copy) | Issuer role holder | Issuer role holder (the buyer issues the credit note) |
| Addressee (`recipient` copy) | Member's party | Producer's party |
| Supplier of the electricity | Community, through the issuer | Producer (the addressee) |
| Buyer of the electricity | Member (the addressee) | Community, through the issuer |
| Payment | Member → issuer IBAN (QR-Rechnung) | Issuer → producer, outside OpenZEV |
| VAT basis | `Zev.vat_mode` | Producer's `Party.vat_registration` + `vat_registration_since` (v1: `not_registered` covering the period only, §4.6) |

PDF placement for Doc B: heading "Gutschrift", a statement that the buyer issues it for the producer's supply of LEG electricity, the producer's block marked as supplier with its VAT statement ("nicht MWST-pflichtig" in v1), and the issuer block marked as buyer and author. The tax adviser reviews this format (§6.1 dependency 2), not only the VAT amount.

**Doc A — `document_kind = invoice`** ("LEG-Rechnung"):

- Generated when the participant has `leg_purchase` quantity > 0 or a fee line in the period.
- Lines: `leg_purchase_energy` per tariff (holder's group price × kWh) and fee lines (§4.4).
- VAT: the community's, from `vat_mode` + `VatRate` on `period_end`, exactly as `generate_invoice`.
- Amounts positive. QR-Rechnung when `total_chf > 0` and the issuer has an IBAN.
- `issuer` = issuer role on `period_end` (`build_issuer`); `recipient` = `participant.party` (`build_recipient`).

**Doc B — `document_kind = producer_credit`** ("Gutschrift"):

- Generated when the participant has `leg_sale` quantity > 0.
- Lines: `leg_sale_energy` only. No fees and no deductions; they belong on Doc A, so each document has one supplier (Doc A: the community; Doc B: the producer).
- Stored negative (line totals and `total_chf` < 0), as with vZEV producer credits, so dashboard revenue (`views_dashboard`, `Sum("total_chf")`) and the status flow keep working. The PDF prints absolute amounts under a credit heading.
- VAT: none in v1 (`vat_rate = 0`, `vat_chf = 0`, `embedded_vat_chf = NULL`). Generated only when the producer's party is `not_registered` (§4.6); the status is copied into the `recipient` snapshot.
- Never a QR-Rechnung, by an explicit `document_kind` check (§6.4, `_build_qr_svg`).
- `issuer` = the document's author (issuer role); `recipient` = the producer's party, printed as the supplier of the electricity. Payout happens by bank transfer outside OpenZEV; `Party` has no IBAN.

Both kinds: no `local_energy`/`grid_energy`/`feed_in` lines (asserted in tests); legacy kWh totals stay `0`; workflow per ADR 0006 unchanged (`draft → approved → sent → paid`; on Doc B the UI labels `paid` as "paid out"); numbers come from the same `Zev.next_invoice_number()` counter; participants see them once sent (`sent_to_participant()`); issuer/recipient frozen from approval on.

#### 4.5.1 Why two documents (decision 2026-10-11)

1. **Two supplies, two suppliers.** Under central settlement a period contains two supplies: community → consumer, and producer → community. Doc A documents the first; Doc B, a credit note issued by the buyer (Gutschrift), documents the second. Operators describe exactly this split: BKW "verrechnen den Erlös und den Bezug des lokal produzierten und genutzten Solarstroms separat"; RWB "Verrechnungen und Gutschriften an Produzenten erfolgen durch die Vertretung"; WWZ "Die Verrechnung und Gutschrift des LEG-Stroms liegt bei der LEG selbst" (§10).
2. **VAT depends on each supplier.** Whether a supply carries VAT depends on its own supplier's status: the community's (`vat_mode`) for Doc A, the producer's for Doc B. ESTV has published no LEG-specific practice. Its ZEV practice (MWST-Branchen-Info 17 §8.4, May 2026, read via secondary sources) taxes a producer's sale when the producer is VAT-registered, and determines the supplier from contracts and external appearance. Offsetting mutual supplies does not remove the duty to report each in full.
3. **One `Invoice` row has one supplier and one VAT basis.** `Invoice` carries one `subtotal_chf`/`vat_rate`/`vat_chf`, one `issuer` and one `recipient`, and `generate_invoice` applies VAT to the subtotal after credits. A combined document would apply the community's VAT rate to the producer's sale, and would need a second VAT block and a second supplier on the model. Doc A and Doc B each fit the existing row as it is.
4. **It survives the tax review.** Whatever the review decides for VAT-registered producers adds VAT to Doc B; it does not change the document model. Netting can be added later as a statement over both documents.

Cost: `document_kind` in the identity key and in every place that assumes one invoice per participant and period (§6.4).

#### 4.5.2 Stale documents and corrections

A LEG document is **stale** when its evidence references a batch that is now `superseded`. Policy per status:

| Status of the stale document | v1 handling |
|---|---|
| `draft` | Replaced by the next generation (as today) |
| `approved`, `sent` | Cancel, then regenerate. On a LEG, regeneration **keeps** a cancelled document that was ever approved (`approved_at` set, sent or not: a PDF can leave OpenZEV before "mark sent"): number, amounts, PDF and frozen parties stay. The new document's `replaces` points to the newest such document of the same participant and kind overlapping its period, and its PDF names it. Only drafts and cancelled documents that were never approved are deleted (`_discard_replaceable_invoices(…, keep_issued=True)` on LEG). The invoice number is no marker of issuance: drafts get numbers at generation and are deleted on regeneration today |
| `paid` | Cannot be cancelled (ADR 0006, `cancel_invoice`), and v1 has no reversal document. Resolved when a manager records a `LegExternalSettlement` (amount, reference, note, who, when; audited). Until then it is unresolved like an approved or sent stale document. The paid document itself stays as issued, and its own participant and kind cannot get a new document for that period (it is still locked by the existing overlap rule) |

**No mixing of revisions.** Generation for a period is refused while any LEG document overlapping it is stale and unresolved: approved or sent ones until cancelled, paid ones until their external settlement is recorded (`leg_stale_documents`, listing each document with the action it needs). So no document is issued from a new revision while an old-revision document of the same period is still open. The existing overlap rule already stops a second live document of the same participant and kind; this rule extends the guard to the other members and the other kind.

Example: Q1 billed quarterly from three monthly batches and sent; a February correction is approved. All Q1 documents become stale. Q1 generation is refused until each approved or sent Q1 document is cancelled and each paid one has its external settlement recorded. Then regeneration issues replacements from January, the corrected February and March, for every participant and kind not held by a paid document. Q2 is unaffected.

### 4.6 Issuer, representative and tax confirmation

LEG setup is complete for a period (the `leg_setup` readiness step, and a precondition of generation; approval checks only status and activation date, §4.3) when:

- `leg_status in {active, ended}` and `leg_activation_date <= period_start`;
- an `issuer` holds on `period_end` (`issuer_on`) and `bank_iban` is set (Doc A QR);
- a `representative` holds on `period_end` (StromVG 17d(5));
- `leg_tax_confirmed_at` is set.

Otherwise `leg_setup_incomplete`, whose `detail` lists the missing items.

**Community confirmation.** `POST /api/v1/zevs/{id}/leg-tax-confirmation/` (manager) sets `leg_tax_confirmed_at`/`_by` and records `zev.leg_tax_confirm`; `DELETE` clears both and records `zev.leg_tax_unconfirm`. It covers only statements about the community, shown verbatim and translated:

1. The community, through its issuer, bills members and credits producers on its own account (central settlement, §1.1).
2. The community's VAT status is the one set in `vat_mode`.

**Producer VAT status, per party.** A community-wide "no producer is VAT-registered" would go stale as producers join or register, so the statement is held per supplier. New field `zev.Party.vat_registration`: `CharField(20)`, `unknown|not_registered|registered`, default `unknown`. It says whether the party is VAT-registered as a supplier. In v1 only LEG producer credits read it; the issuer's own VAT setup stays on the ZEV (ADR 0028 decision 6). It is edited on the party (audited by the existing party update mixin) and shown in the party form on LEG ZEVs.

VAT status is decided by the supply period, not the generation date: a producer registered in March and deregistered in July must not get a VAT-free credit for March in October. So the status carries the date it applies from: `zev.Party.vat_registration_since`, `DateField`, null. It is required whenever `vat_registration != unknown`, and changing the status requires a new date.

- Doc B for a producer is generated only when that producer's party is `not_registered` **and** `vat_registration_since <= period_start`. `unknown` → `leg_producer_vat_unknown`. `registered` → `leg_producer_vat_registered` (VAT on producer credits is out of scope). `not_registered` since a date after `period_start` → `leg_producer_vat_not_established`: v1 keeps no history, so the status during that period cannot be established, and retrospective credits for it are refused. Conservative in both directions.
- Status and date are copied into the `recipient` snapshot, so an approved document keeps the declaration it was issued under.
- Readiness (`leg_setup`) lists the producers with sale quantities in the period whose declaration does not cover it.

Implementation dependency 2 (§6.1) stays: before shipping, a tax adviser signs off the confirmation text, the dated producer-declaration rule and the Doc B format. The confirmation and the declarations document an arrangement the adviser approved; they do not replace that review.

### 4.7 Enforcement map (what the DB guarantees vs the service)

A `CheckConstraint` cannot see another table's `zev_type`, and `clean()` is not called on every save (imports, jobs, bulk ops bypass it). Each invariant states its enforcement:

| Invariant | DB | Service (transactional) | `clean()` |
|---|---|---|---|
| `leg_*` fields default on non-LEG | — | `ZevSerializer` | yes |
| `zev_type` locked once data exists | — | `ZevSerializer.validate` | — |
| LEG assignment `personal`; `tariff_group` only on LEG | — | assignment serializer | yes |
| No overlapping windows per point | — | existing `_validate_no_overlap` (`save()` and `clean()`) | yes |
| `leg_*` tariffs only on LEG; legacy types never on LEG; one flat band | — | tariff serializer + pricing | yes |
| Source rows are either non-cancellation with a non-null, non-negative value or cancellation with a null value; `interval_end > interval_start`; quantity point null only for `reconcile_only` | `CheckConstraint` | re-validated on import; assembly copies only non-cancellation rows into quantities | — |
| Source tombstones belong only to cancellation messages | — | import | — |
| Value point belongs to the LEG and lies in an assignment window; null point only for `E31` community aggregates | — | import | — |
| All three products of each assigned point's flow complete over its window | — | reconcile, and again at generation against current assignments | — |
| One stored message per `(zev, sender_eic, document_id)` | `UniqueConstraint` | import (idempotent re-upload, `leg_document_id_conflict`) | — |
| Message community, type, process and receiver match the LEG | — | import | — |
| Newest `Creation` wins per point, flow, product and interval; cancellations are tombstones; equal `Creation` with disagreeing entries blocks | — | assembly | — |
| A later message that changes an approved batch's result blocks generation | — | re-assembly check after each import, at approval and in `may_generate` (`leg_newer_source_data`) | — |
| No overlapping approved batches; a correction covers what it replaces | partial `UniqueConstraint` (identical periods only) | `approve_batch` under the `Zev` row lock (authoritative) | — |
| One live document per `(participant, period, kind)` | — | `_discard_replaceable_invoices` (as today) | — |
| Exactly one price per series, group and day | — | `engine_leg` (`leg_no_tariff` / `leg_ambiguous_tariff`) | — |
| Setup complete | — | generate (approval checks status + activation only) | — |
| No generation next to unresolved stale documents (approved/sent not cancelled, paid without `LegExternalSettlement`) | `OneToOne` on the settlement record | generate (`leg_stale_documents`) | — |
| Producer declaration covers the period | — | generate (`leg_producer_vat_*`) | `Party.clean()`: `vat_registration_since` required unless `unknown` |
| Doc B only for `not_registered` producers | — | generate | — |
| Approved LEG documents never deleted by regeneration | — | `_discard_replaceable_invoices(keep_issued=True)`, keyed on `approved_at` | — |

---

## 5. API contracts

Conventions, all existing:

- Flat DRF routes under `/api/v1/`, scoped by `ZevScopedQuerySetMixin` and narrowed with `?zev_id=`; objects of other ZEVs are `404`.
- Viewers may call reads. Writes on a disabled ZEV are rejected for non-admins, also in custom actions.
- Coded errors are `{"code": ..., "error": ...}` plus context keys, as `DynamicTariffError.as_dict()`; the frontend parses them in `lib/api/errors.ts`.
- No `Idempotency-Key` header: generation is idempotent by draft replacement, and approval is serialised by the `Zev` row lock.

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/zevs/{id}/` | PATCH/PUT | manager | LEG fields and rules (§4.1) |
| `/api/v1/zevs/{id}/leg-tax-confirmation/` | POST, DELETE | manager | §4.6 |
| `/api/v1/metering-points/`, `/api/v1/metering-point-assignments/` | existing | existing | Assignment accepts `tariff_group`; LEG rules (§4.2). Deleting a point with settlement quantities → `400 leg_point_referenced` |
| `/api/v1/tariffs/` | existing | existing | `tariff_group`; LEG rules (§4.4) |
| `/api/v1/parties/` | existing | existing | `vat_registration`, `vat_registration_since` (§4.6) |
| `/api/v1/leg-source-messages/` | GET | manager, viewer | List with sender, `document_id`, `document_type`, `document_function`, `source_created_at`, report period, and the batches that use each message |
| `/api/v1/leg-source-messages/` | POST (multipart: `zev`, one or more `files`) | manager | Each file parsed on its own (§4.3): `201` per stored message, "already imported" for an identical re-upload, or the file's findings with nothing stored for it. The response lists the outcome per file |
| `/api/v1/leg-source-messages/{id}/` | GET | manager, viewer | Messages are append-only; there is no DELETE (§4.3) |
| `/api/v1/leg-source-messages/{id}/cancellation-resolutions/` | GET | manager, viewer | The message's resolutions, oldest first, with evidence and supersession |
| `/api/v1/leg-source-messages/{id}/cancellation-resolutions/` | POST multipart `{outcome, keys?, evidence_reference, evidence_file?, reason, supersedes?}` | manager | Cancellations without listed keys only (`leg_resolution_not_applicable` otherwise); `evidence_reference` and `reason` required (`leg_resolution_evidence_required`); `supersedes` must name the current resolution when one exists (`409 leg_resolution_not_current`). Audited. No PATCH or DELETE |
| `/api/v1/leg-settlement-batches/` | GET | manager, viewer | List with `review_state`, `revision`, `findings`, `latest_source_created_at`, `superseded_by`, `may_preview` |
| `/api/v1/leg-settlement-batches/` | POST `{zev, period_start, period_end}` | manager | Assembles a batch from the stored messages (§4.3); `201` `assembled`, or `400 leg_nothing_to_assemble` |
| `/api/v1/leg-settlement-batches/{id}/` | GET / DELETE | manager, viewer / manager | DELETE only while `assembled` or `reconciled` (`leg_batch_locked`) |
| `/api/v1/leg-settlement-batches/{id}/reconcile/` | POST | manager | `200` with the batch: `reconciled`, or still `assembled` with findings |
| `/api/v1/leg-settlement-batches/{id}/approve/` | POST `{override_reason?, override_reference?}` | manager | §4.3 approval; the override reason is required when overridable findings exist |
| `/api/v1/leg-settlement-batches/{id}/preview/` | GET | manager, viewer | Requires `may_preview` (`400 leg_unreconciled` otherwise). Prices the batch's own period from this batch alone: per `(participant, document_kind)` kWh, lines, totals and blockers. Writes nothing |
| `/api/v1/leg-settlement-quantities/?batch=&metering_point=` | GET | manager, viewer; participant link | Participants see only member-point rows of approved, non-superseded batches inside their own assignment windows (civil day of `interval_start`), shaped after `MeterReadingViewSet._participant_q`. Community rows are never visible to participants |
| `/api/v1/invoices/generate/` | POST `{participant_id, period_start, period_end, document_kind?}` | manager | `document_kind` defaults to `invoice`; on non-LEG anything else → `400 leg_document_kind_invalid`. LEG: requires `may_generate` (incl. completeness and no unresolved stale documents); no document of the requested kind to issue under §4.5 → `400 leg_nothing_to_bill`, writes nothing; otherwise one document per call; sets `replaces` (§4.5.2) |
| `/api/v1/invoices/{id}/leg-external-settlement/` | POST `{amount_chf, reference, note?}` | manager | Records a `LegExternalSettlement` for a paid stale LEG document (`leg_settlement_not_applicable` otherwise); audited `invoice.leg_external_settlement`; `409` if one exists. Read back as a nested field on the invoice |
| `/api/v1/invoices/generate-all/` | POST | manager | LEG: a preflight (setup + coverage, `400` coded) replaces `preflight_dynamic_prices`; queues the existing task |
| `/api/v1/invoices/` | GET | existing | `document_kind` field and `?document_kind=` filter |
| `/api/v1/invoices/readiness/`, `/attention/`, `/period-overview/` | GET | existing | LEG branch (§6.4) |
| `/api/v1/invoices/annual-report/`, `/annual-statement/`, `/financial-summary/` | GET | existing | LEG ZEV → `400 leg_report_unsupported` |

Stable `code`s:

- Setup and configuration: `leg_fields_on_non_leg`, `leg_zev_type_locked`, `leg_community_allocation`, `leg_tariff_type`, `leg_setup_incomplete`.
- Import: `leg_parse_error`, `leg_wrong_process`, `leg_community_type_unsupported`, `leg_community_id_missing`, `leg_community_mismatch`, `leg_receiver_mismatch`, `leg_unknown_product`, `leg_position_mismatch`, `leg_unmapped_point`, `leg_flow_mismatch`, `leg_outside_assignment`, `leg_document_id_conflict`, `leg_resolution_not_applicable`, `leg_resolution_evidence_required`, `leg_resolution_not_current`.
- Batches: `leg_nothing_to_assemble`, `leg_incomplete_series`, `leg_point_balance`, `leg_community_balance`, `leg_aggregate_mismatch`, `leg_missing_seller_data`, `leg_cancelled_values`, `leg_cancellation_unresolved`, `leg_ambiguous_source`, `leg_temporary_values`, `leg_before_plausibilisation`, `leg_unreconciled`, `leg_override_required`, `leg_partial_supersede`, `leg_batch_locked`, `leg_point_referenced`. Informational: `leg_estimated_values`, `leg_corrections_possible_until`, `leg_newer_source_unchanged`.
- Generation and documents: `leg_period_not_covered`, `leg_newer_source_data`, `leg_stale_documents`, `leg_no_tariff`, `leg_ambiguous_tariff`, `leg_producer_vat_unknown`, `leg_producer_vat_registered`, `leg_producer_vat_not_established`, `leg_settlement_not_applicable`, `leg_nothing_to_bill`, `leg_document_kind_invalid`, `leg_report_unsupported`.

---

## 6. Async and integration behavior

### 6.1 Import and dependencies

Work in this order:

1. **Study the standard.** The SDAT-CH 2025 documents (Hauptdokument, Messdatenaustauschprozesse V2, Annexes 3 and 4) and the VSE LEG industry document (BD LEG 2025 V2) were read for this revision (§10). Still to obtain: the 2025 XSD package and any official example files for §1.12/§1.13. Annex 4 names example files after the process chapters, but whether LEG examples exist is unconfirmed.
2. **Freeze the canonical import contract** of §4.3 (`LegSourceMessage`, `LegSourceValue`, the series mapping, the `CommunityID` and receiver-EIC identities) before any parser code.
3. **Confirm delivery rights and route per VNB:** who receives the data (the representative, or a mandated service provider), under which EIC-X, and how members' consent is documented. BD LEG has members confirm to the representative that it may receive their metering data, and SDAT-CH §1.12 requires the receiver to be registered with an EIC and authorised. Whether the data comes directly or through a data hub is per VNB.
4. **Conformance gate:** the parser passes the official material (if examples exist) and **two independent real deliveries**, from different VNBs or over different routes (direct vs hub), each reconciled against that VNB's statement. A parser that has passed one VNB's export is an integration with that VNB, not proof of general SDAT-CH support. The user guide lists the verified senders and routes.
5. Tax and contract sign-off (§4.5–§4.6).
6. The ADR (§1.2).

**Licensing.** The SDAT-CH documents, schemas and examples are © VSE: "Gewerbliche Nutzung der Unterlagen ist nur mit Zustimmung vom VSE/AES und gegen Vergütung erlaubt. Ausser für den Eigengebrauch ist jedes Kopieren, Verteilen oder anderer Gebrauch dieser Dokumente als durch den bestimmungsgemässen Empfänger untersagt." Neither the XSDs nor official or real example files go into the repository without VSE consent (real files also carry personal data). Repository tests use self-authored messages built from the documented structure; the official material and anonymised real deliveries are used in local conformance runs.

Behaviour:

- **Transport** (v1): manual upload of one or more `.xml` or `.xml.gz` files per request. Later transports, such as hub download or FTPES (the channel SDAT-CH §4.13 prescribes), only deliver files to the same parser; they are out of scope.
- **Parser profiles:** `sdat_ch_2025_leg` is the common parser for every VNB that follows the standard (`metering/importers/leg_sdat.py`). A VNB-specific CSV or portal export gets its own named profile only with a sample, a field mapping and tests. Every profile produces `LegSourceValue` rows, and nothing downstream knows which profile was used.
- Import runs in the request, one transaction per file. A Celery path (`metering.tasks.import_leg_messages`) is added only if real deliveries exceed what the request can handle. A file that fails stores nothing (§4.3).

### 6.2 Generation

- `invoices/engine_leg.py`:
  - `price_leg_period(zev, period_start, period_end, *, batches=None) -> LegPricing`: pure, no writes. Preview and generation both use it.
  - `generate_leg_document(participant, period_start, period_end, document_kind, generation_context=None) -> Invoice`.
  - `generate_leg_documents_for_zev(zev, period_start, period_end) -> BulkGenerationResult`.
- Dispatch keeps one entry point for the view, the Celery task (`generate_zev_invoices_task`) and `seed_demo`: `generate_invoice(participant, period_start, period_end, generation_context=None, *, document_kind="invoice")` delegates when `participant.zev.zev_type == LEG`; `generate_invoices_for_zev` delegates the same way.
- `LegBillingError(ValueError)` carries `code` + `as_dict()`. `InvoiceViewSet.generate` answers it with `400` before the generic `ValueError` branch, which today replies `409 "may already exist"` to any `ValueError`.
- Bulk: per participant, Doc A then Doc B. `leg_nothing_to_bill` is skipped for that kind, not a failure. Failures are isolated per participant (ADR 0011), and `invoices` holds documents of both kinds.

### 6.3 PDF and email

- Existing DB template with LEG blocks keyed on `zev.zev_type` and `document_kind`: heading ("LEG-Rechnung" / "Gutschrift"), party blocks labelled per the roles table (§4.5), `leg_community_id`, period, batch revisions from the evidence, kWh × price per tariff and group, fees and VAT (Doc A only), the producer's VAT statement (Doc B), "replaces no. …" when `replaces` is set, and the note that the VNB bills network and residual supply separately. The energy-summary charts (`pdf_stats`, `pdf_charts`), built on local/grid lines, are omitted for LEG.
- QR-Rechnung only when `document_kind == invoice and total_chf > 0` (explicit rule, §4.5).
- Email: Doc A uses `invoice_email`. Doc B uses a new template key `producer_credit_email` with defaults in EN/DE/FR/IT (shaped after the magic-link defaults); `{total_chf}` renders as an absolute amount.
- Field catalog (`field_catalog_data.py`): `invoice.document_kind`, `zev.leg_community_id`.

### 6.4 Existing code paths that change

| Path | Today | LEG change |
|---|---|---|
| `invoices/engine.py` `_discard_replaceable_invoices`, `locked_overlapping_invoices` | Participant + overlapping period; deletes drafts and every cancelled overlap | + `document_kind`; on LEG `keep_issued=True` keeps cancelled documents with `approved_at` (§4.5.2) |
| `invoices/workflow.py` `approve_invoice` | Freezes the issuer/recipient copy | Also stamps `approved_at` (all ZEV types) |
| `invoices/document_parties.py` | `recipient` copy without VAT status | Copy gains `vat_registration` and `vat_registration_since` (Doc B) |
| `invoices/readiness.py` | Steps `metering`, `assignments`, `tariffs` read `MeterReading`, assignments and local/grid tariffs; invoice steps count one invoice per participant | LEG: `leg_setup` (incl. producers whose declaration does not cover the period) and `leg_settlement` (date coverage, series completeness against current assignments, overridden findings, later changes to approved batches with the documents they affect, unresolved stale documents with the action each needs) replace `metering`; `tariffs` checks LEG price resolution for every group in use; `assignments` unchanged; invoice steps and `generation_conflicts` count documents per `(participant, kind)` |
| `invoices/period_overview.py` | One row per participant (`invoice_map.setdefault(invoice.participant_id, …)`) | LEG: one row per `(participant, kind)` with something to bill or an existing document; rows gain `document_kind`; "metering data complete" means every assigned point has quantities in the covering batches |
| `compute_attention`, `compute_period_list` | Built on readiness | Inherit the LEG branch |
| `financial_summary.py`, `annual_statement.py`, `annual_report.py`, `metering/analytics.py` energy balance | Local/grid lines; OpenZEV allocation | LEG: `leg_report_unsupported`; hidden in UI |
| `views_dashboard.py` revenue | `Sum("total_chf")` over sent/paid | Unchanged; Doc B is negative and nets like vZEV producer credits |
| `invoices/pdf.py` `_build_qr_svg` | Negative totals skipped by a swallowed `qrbill` exception | Explicit rule (§6.3) |
| `mcp_server/tools` `explain_invoice`, `find_invoices`, `period_readiness` | vZEV only | Explain LEG lines from the evidence; `document_kind` in results |
| `zev/buildings.py` | Every non-vZEV → one building | Only `ZEV` → one building |
| `ZevSerializer` | `zev_type` writable | Lock + LEG fields (§4.1) |
| `zev/transfer/schema.py` | `FORMAT_VERSION = 7` | Format 8: new fields in `ZEV_FIELDS` (not the tax confirmation: like `participant_invoice_access`, it is a decision for the instance that runs the ZEV), `PARTY_FIELDS` (`vat_registration`, `vat_registration_since`), `ASSIGNMENT_FIELDS`, `TARIFF_FIELDS`, `INVOICE_FIELDS` (`approved_at`; `replaces` by invoice number); `LegExternalSettlement` travels with its invoice; new section `leg_settlement` (source messages with their files and values, cancellation resolutions with their evidence files, batches, quantities; depends on `metering_points`); evidence travels in the `invoices` section keyed by batch `(period_start, period_end, revision)` and is dropped with a warning when the archive has no `leg_settlement` section. Older archives import with defaults |
| `backups/registry.py` | `CoverageTests` fail on any unregistered model | Register `metering.LegSourceMessage`, `LegSourceValue`, `LegCancellationResolution`, `LegSettlementBatch` and `LegSettlementQuantity` after `zev.MeteringPoint`, and `invoices.InvoiceLegSettlementEvidence` and `invoices.LegExternalSettlement` after `invoices.Invoice`; `source_file` is copied like other file fields |
| `zev/purge.py` | Collects invoice PDFs and export files for deletion | Also collects `LegSourceMessage.source_file` and `LegCancellationResolution.evidence_file` |
| Audit | — | `leg_source_message.create`; `leg_cancellation_resolution.create`; `leg_settlement_batch.create`/`.delete` (mixins), `.reconcile`, `.approve` (override + superseded IDs); `zev.leg_tax_confirm`/`.leg_tax_unconfirm`; `invoice.leg_external_settlement`; `invoice.generate` metadata gains `document_kind` |
| `seed_demo` | ZEV + vZEV | Add a LEG demo community fed by self-authored SDAT-CH 2025 LEG messages, for screenshots and the user guide |
| Baseline specs (update on implementation) | — | tariffs-and-billing-engine, invoice-lifecycle-and-communication, metering-point-management, metering-import-and-quality, admin-governance-and-settings, zev-transfer-archive, buildings-and-sites, backup-and-restore |

---

## 7. Frontend

- **ZEV creation** (`ZevListPage.tsx` wizard, `VerifyEmailPage.tsx` self-setup): `leg` option.
- **ZEV settings** (`ZevSettingsPage.tsx`, `components/ZevGeneralSettingsFields.tsx`): for `zev_type == "leg"` show `leg_community_id`, `leg_receiver_eic`, `leg_status`, `leg_activation_date`, and a community-confirmation card (state, who, when, confirm/withdraw with the statements of §4.6). The VNB is the existing grid-operator field (`features/zev/GridOperatorField.tsx`). Issuer and representative stay in the People & access section (`ZevPeopleSection.tsx`); LEG settings show a hint when either is missing. The party form (`features/zev/PartyFormModal.tsx`) shows `vat_registration` and `vat_registration_since` on LEG ZEVs.
- **Metering points** (`MeteringPointsPage.tsx`, `features/meteringPoints`): on a LEG the assignment form shows `tariff_group` and hides allocation mode; windows that start after today are labelled "pending activation".
- **Tariffs** (`TariffsPage.tsx`, `features/tariffs`): energy types filtered by `zev_type`; `tariff_group` field on LEG; VSE import and dynamic sources hidden on LEG.
- **Settlement** (`ImportsPage.tsx`, `features/imports`): LEG ZEVs get a settlement section with upload of one or more files (outcome per file) → message list (sender, document ID, function, creation time, report period) → assemble a period → findings (blocking, overridable, informational) → reconcile → preview (per member: purchase/sale kWh, charge, credit, fees, blockers) → approve (disabled until `reconciled`; an override reason is required when overridable findings exist), and a batch list with revisions, superseded state and a "newer data available" marker. The raw SDAT import stays for measured data.
- **Billing** (`BillingPeriodsPage.tsx`, `features/invoices/InvoicePeriodRowsTable.tsx`, `InvoicesPage.tsx`, `InvoiceDetailPage.tsx`, `MyInvoicesPage.tsx`): document-kind label; period rows per `(participant, kind)`; stale documents marked, with the cancel action offered for approved/sent and a "record external settlement" form (amount suggested from the preview, reference, note) for paid; the detail page hides local/grid/feed-in sections, labels the parties per the roles table (§4.5), shows LEG lines with their evidence (batch, revision, override) and links `replaces`/`replaced_by`; Doc B shows absolute amounts as a credit and "paid out" for `paid`. `ReportsPage.tsx` hides the reports a LEG does not support.
- **Types** (`frontend/src/types/api.ts`): `zev_type` unions (three in `api.ts`, plus the cast in `VerifyEmailPage.tsx`) gain `'leg'`; LEG fields on the ZEV types; `Invoice.document_kind`, the two totals, `approved_at`, `replaces`/`replaced_by` and `leg_external_settlement: LegExternalSettlement | null`; `vat_registration`/`vat_registration_since` on the party type; `tariff_group` on assignment and tariff types; new LEG energy and item types.

```typescript
type ZevType = 'zev' | 'vzev' | 'leg'
type InvoiceDocumentKind = 'invoice' | 'producer_credit'

interface LegFinding {
  code: string; message: string;
  kind: 'blocking' | 'overridable' | 'informational';
  meter_id?: string; interval_start?: string
}
interface LegSourceMessage {
  id: string; zev: string; source_filename: string; parser_profile: string;
  document_id: string; document_type: 'E66' | 'E31';
  document_function: '9' | '5' | '1';  // original | replace | cancellation
  source_created_at: string; sender_eic: string; receiver_eic: string;
  community_id: string; community_type: 'CT01';
  report_start: string; report_end: string; received_at: string;
}
interface LegSettlementBatch {
  id: string; zev: string; period_start: string; period_end: string;
  revision: number; review_state: 'assembled' | 'reconciled' | 'approved' | 'superseded';
  assembled_at: string; latest_source_created_at: string;
  findings: LegFinding[]; approved_at: string | null;
  override_reason: string; override_reference: string;
  superseded_by: string | null; may_preview: boolean;
}
interface LegSettlementQuantity {
  id: string; batch: string; source_point_id: string;
  metering_point: string | null;  // null for community rows
  flow: 'consumption' | 'production';
  product: '2404050010123' | '2404050010124' | '8716867000030';
  series: 'leg_purchase' | 'leg_sale' | 'reconcile_only';
  interval_start: string; interval_end: string;
  quantity_kwh: string; condition: '' | '21' | '56';
}
interface LegExternalSettlement {
  amount_chf: string; reference: string; note: string;
  recorded_by: string | null; recorded_at: string;
}
```

- **API client:** `lib/api/metering.ts` (source messages, assemble, batches, quantities, reconcile, approve, preview), `lib/api/zev.ts` (tax confirmation), `lib/api/invoices.ts` (`document_kind`), `lib/api/errors.ts` (LEG codes, like `dynamic_price_gap`).
- **i18n** (de/fr/it/en), next to the existing keys: `pages.zevs.zevTypes.leg`, `pages.tariffs.energyTypes.leg_purchase|leg_sale`, `invoice.status.paidOut`, `invoice.documentKind.invoice|producer_credit`; new `leg.*` keys for settings, tax confirmation, settlement, reconcile, `leg.findings.<code>`, override, `tariffGroup`, `noOffsetting`, `vnbBilledSeparately`. Line descriptions come from the backend (`_build_description`), so item types need no frontend keys.
- **User guide:** a LEG chapter (setup, members and points, settlement import, documents), plus updates to ZEV setup, metering points, tariffs and invoice management.

---

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Incomplete, unchecked or since-corrected data priced | High | Immutable batches; complete series and balance checks; temporary values and early approval only with an audited override; a later replacement or cancellation that changes an approved batch blocks generation until a new revision is approved; ties block; no auto-approval |
| Consumer-only billing | High | Producer credits are a first-class document; `leg_missing_seller_data`; separate sale tariff + group key |
| Double-billing VNB parts | High | Only LEG energy and fees on LEG documents; legacy energy types rejected on LEG; asserted in tests |
| Incomplete settlement data billed low | High | Expected-series completeness at reconcile and again at generation against current assignments; date coverage alone never suffices |
| Issued document lost on correction | High | LEG regeneration keeps cancelled documents that were ever approved (`approved_at`); `replaces` links the correction; paid documents are not corrected in v1 |
| Revisions mixed across documents | Medium | Generation refused while any stale document in the period is unresolved; a paid one is resolved only by a recorded external settlement |
| Wrong credit VAT | High | Doc B has one supplier and no VAT in v1; producer declaration (`vat_registration` + `_since`) must cover the supply period; adviser sign-off of format and rule before shipping |
| Second document breaks an "one invoice per participant" assumption | High | `document_kind` in the identity key; every known assumption listed in §6.4 and tested |
| VNB format variance | Medium | One standard parser (`sdat_ch_2025_leg`); deviations only as named profiles with samples and tests; two independent real deliveries before claiming general support (§6.1) |
| Billing from information-only or temporary data | High | No "final" flag exists. Temporary values are overridable findings; the early-approval date is a warning heuristic, never proof of checking; corrections after approval block billing until a new revision is approved (§4.3, §4.5.2) |
| Collective-billing LEG billed as individual | High | `CommunityType CT02` refused at import |
| Overlapping or partial corrections double-bill | Medium | Approval under the `Zev` row lock; `leg_partial_supersede`; stale documents flagged |
| ZEV-in-LEG as type switch | Medium | Explicit v1 rejection; `zev_type` locked once data exists |
| Participant sees a previous holder's data | Medium | Quantities windowed by the participant's own assignments, as readings are |
| Cross-LEG data leak via IDs | Medium | Scoping mixin `404`; tests alter IDs |

---

## 9. Test plan

### Backend — `invoices/test_leg_engine.py` (`TestLegEngine`)

| Test | Asserts |
|---|---|
| `test_imported_quantities_price_both_sides` | Given imported A=4.8, B=3.2 purchase and seller total 8, Doc A charges 4.8/3.2 at the purchase price and Doc B credits 8 at the sale price (the engine prices imports; it does not invent pro-rata) |
| `test_prosumer_gets_invoice_and_producer_credit` | Same participant and period → one `invoice` and one `producer_credit`; no offset line; regenerating one kind leaves the other untouched |
| `test_prosumer_switches_direction_between_intervals` | Buys in i1, sells in i2: Doc A covers i1, Doc B covers i2 |
| `test_member_with_two_points` | Two points of one participant → one document per kind, lines from both |
| `test_price_group_follows_assignment_window` | Group change mid-period through a new window prices each interval at its window's group |
| `test_zero_energy_with_fixed_fee` | Fee-only Doc A; no Doc B |
| `test_nothing_to_bill_per_kind` | No purchase quantity or fee → `leg_nothing_to_bill` for Doc A; no sale quantity → the same for Doc B; single generation answers `400` without writing or deleting documents, bulk skips that kind without a failure |
| `test_group_scoped_fee_applies_only_to_group_months` | Fee with group G charged only in months with a G assignment |
| `test_mid_period_tariff_change_priced_per_interval` | A tariff change or group change mid-period prices each interval at the price valid for it |
| `test_missing_and_ambiguous_tariff` | `leg_no_tariff`, `leg_ambiguous_tariff` block generation and show in preview; batch approval unaffected |
| `test_assignment_added_after_approval_blocks_generation` | New window over an approved period without rows → `leg_incomplete_series` at generation |
| `test_producer_vat_status_gates_producer_credit` | `unknown` → `leg_producer_vat_unknown`, `registered` → `leg_producer_vat_registered`, `not_registered` since before the period → Doc B with status and date in the recipient copy; Doc A unaffected |
| `test_producer_declaration_after_period_start_refused` | `not_registered` since July, March credit generated in October → `leg_producer_vat_not_established` |
| `test_roles_on_producer_credit` | Doc B copy: issuer = issuer role (author/buyer), recipient = producer (supplier) |
| `test_no_local_grid_or_feed_in_lines` | No legacy item types; `reconcile_only` series never priced |
| `test_producer_credit_negative_without_vat_or_qr` | Doc B totals < 0, VAT 0, no QR even with an issuer IBAN |
| `test_invoice_vat_follows_vat_mode` | Doc A VAT for each `vat_mode` |
| `test_period_needs_full_batch_coverage` | Three approved monthly batches price a quarter; a missing month → `leg_period_not_covered` |
| `test_superseded_batch_never_prices` | Only the approving batch's quantities are used |
| `test_stale_sent_document_blocks_generation_in_period` | After a correction, generation of any document overlapping the period → `leg_stale_documents` until the approved/sent stale ones are cancelled; other periods unaffected |
| `test_partial_quarter_then_monthly_correction` | Q1 sent from three monthly batches, February corrected: Q1 blocked, cancel all, regenerate from Jan + corrected Feb + Mar |
| `test_cancelled_approved_document_kept_on_regeneration` | Cancelled document with `approved_at`, sent or not, keeps number, amounts and PDF; new document `replaces` it; drafts and never-approved cancelled ones are deleted |
| `test_approve_stamps_approved_at` | `approve_invoice` sets `approved_at` on LEG and vZEV invoices; vZEV regeneration behaviour unchanged |
| `test_paid_stale_blocks_until_external_settlement` | Paid stale document → `leg_stale_documents` for the period; after a `LegExternalSettlement` is recorded, generation for the other participants and kinds proceeds, while the paid document's own participant and kind stay locked |
| `test_external_settlement_only_for_paid_stale` | Recording on a non-LEG, unpaid or non-stale document → `leg_settlement_not_applicable`; a second record → `409`; the record is audited |
| `test_decimal_rounding_and_dst` | Deterministic rounding; UTC storage, civil-day pricing on DST days; source literal retained |
| `test_generate_invoice_dispatch` | LEG dispatches to `engine_leg`; vZEV rejects `producer_credit`; vZEV results unchanged |

### Backend — `metering/test_leg_settlement.py` (`TestLegSettlement`)

SDAT-CH conformance, on self-authored messages (§6.1 licensing):

| Test | Asserts |
|---|---|
| `test_parse_error_stores_nothing` | Malformed gzip/XML, schema-invalid content and hardening-limit violations → `400 leg_parse_error`, nothing stored for the file |
| `test_ct01_accepted_ct02_refused` | `CT02` → `leg_community_type_unsupported`, nothing stored |
| `test_product_and_flow_map_to_series` | Local on consumption → `leg_purchase`, local on production → `leg_sale`, residual and total → `reconcile_only`; an unknown product → `leg_unknown_product` |
| `test_community_id_and_receiver_checked` | Wrong or missing `CommunityID`, wrong receiver EIC, wrong receiver role or business reason (e.g. a supplier's `E88` residual flow) refused |
| `test_dst_days_92_and_100_positions` | Spring and autumn days parse to 92 and 100 correct UTC intervals; a mismatching count → `leg_position_mismatch` |
| `test_position_not_element_order` | Observations out of document order land on their `Position` |
| `test_split_files_assemble_to_one_batch` | Two messages split by metering point form one complete batch |
| `test_replace_with_newer_creation_wins` | A `replace` with a newer `Creation` wins; an older `Creation` arriving later does not |
| `test_cancellation_is_tombstone` | Listed keys stored as `LegSourceValue(is_cancellation=True, quantity_kwh=None)` with message provenance and no invented volume; newer than their values, they leave gaps for exactly those keys (`leg_cancelled_values`, `leg_incomplete_series`) and create no quantities; a later original or replacement fills them again |
| `test_source_value_quantity_constraint` | DB accepts zero/non-negative value rows and null tombstones; rejects null value rows, negative values and non-null tombstones; import rejects tombstones on original/replacement messages |
| `test_cancellation_without_keys_blocks_until_resolved` | A cancellation listing no keys creates no tombstones, blocks every overlapping batch with `leg_cancellation_unresolved` (approved ones too, so generation stops), and is cleared only by a resolution with an evidence reference: listed keys become tombstones marked `manually_resolved`, or `no_effect` |
| `test_resolution_needs_evidence` | A resolution without `evidence_reference` → `leg_resolution_evidence_required`; the cancellation stays blocking |
| `test_resolution_superseded_not_edited` | A second resolution must name the current one (`409 leg_resolution_not_current` otherwise); the first stays on record; batches whose selected data changes get `leg_newer_source_data`; there is no PATCH or DELETE |
| `test_superseding_resolution_after_approval` | Resolve a cancellation with listed keys, approve a batch, then supersede the resolution with a different one: generation for the period blocks at once (`leg_newer_source_data`); the old decision and its evidence file stay retrievable; a new batch revision is required because selected values change |
| `test_concurrent_supersede_conflict` | Two requests supersede the same current resolution; the second names a no-longer-current decision → `409 leg_resolution_not_current`, and only one new decision is stored |
| `test_messages_cannot_be_deleted` | No delete endpoint, including for an unreferenced cancellation |
| `test_equal_creation_conflict_blocks` | Two messages with the same `Creation` and different values for a key → `leg_ambiguous_source`, whatever the upload order; identical entries pass |
| `test_quantity_records_winning_message` | Each quantity's `source_value` points at the message whose value won, across split and replacement files |
| `test_missing_values_never_zero` | An absent position is a gap (`leg_incomplete_series`), not zero |
| `test_temporary_overridable_estimated_informational` | `Condition 21` needs an override to approve; `56` is reported only |
| `test_before_plausibilisation_deadline_overridable` | Assembling before the 5th working day after the month needs an override |
| `test_point_and_community_balances` | Total ≠ residual + local → `leg_point_balance`; Σ local consumption ≠ Σ local production → `leg_community_balance`; `E31` sums ≠ member sums → `leg_aggregate_mismatch` |
| `test_two_senders_same_canonical_quantities` | Equivalent messages from two VNB sender EICs assemble to identical quantities |
| `test_same_document_reupload_idempotent` | Same `DocumentID` and bytes → acknowledged once; same ID, other bytes → `leg_document_id_conflict` |
| `test_changed_later_message_blocks_generation` | A replacement or cancellation after approval that changes a selected value → `leg_newer_source_data`; generation and approval refused until a new revision is approved; issued documents listed as affected |
| `test_unchanged_later_message_informational` | A later message repeating the selected values → `leg_newer_source_unchanged` only; generation proceeds |
| `test_plausibilisation_date_never_changes_state` | Passing the early-approval date changes no batch state or finding by itself |
| `test_unreconciled_preview_and_approval_refused` | Preview on `assembled`/`superseded`, or approval on any state other than `reconciled`, → `400 leg_unreconciled`, no state change |

Lifecycle: `test_unmapped_point_rejected_naming_id`, `test_point_of_other_zev_reported_as_unmapped`, `test_flow_mismatch_rejected`, `test_community_aggregates_stored_without_point`, `test_value_outside_assignment_rejected`, `test_hard_errors_store_nothing_per_file`, `test_reassembly_creates_revision`, `test_single_interval_does_not_make_point_complete`, `test_point_missing_from_messages_is_incomplete`, `test_missing_seller_data`, `test_approval_ignores_tariffs_and_tax`, `test_override_required_and_audited`, `test_partial_supersede_rejected`, `test_supersede_marks_old_before_approving_new`, `test_concurrent_approvals_serialise` (PostgreSQL leg), `test_delete_only_before_approval`, `test_point_with_quantities_cannot_be_deleted`, `test_zev_purge_removes_batches_and_files`.

### Backend — `zev/test_leg_validation.py` (`TestLegValidation`)

`test_leg_fields_rejected_on_non_leg`, `test_zev_type_locked_once_data_exists`, `test_grid_operator_required_after_draft`, `test_activation_date_required_for_active`, `test_leg_assignment_must_be_personal`, `test_tariff_group_blank_on_non_leg`, `test_leg_tariff_rejected_on_non_leg`, `test_legacy_tariff_rejected_on_leg`, `test_leg_tariff_single_flat_band`, `test_leg_buildings_per_address`, `test_eic_x_code_length`, `test_vat_registration_since_required_unless_unknown`, `test_setup_incomplete_lists_missing_items`, `test_tax_confirmation_action_audited`.

### Backend — `invoices/test_leg_readiness.py` (`TestLegReadiness`)

LEG steps and `next_action`; period-overview rows per `(participant, kind)` with eligibility per kind; attention items; vZEV payloads unchanged.

### Backend — `invoices/test_leg_permissions.py` (`TestLegPermissions`)

Manager of LEG-1 gets `404` on LEG-2 batch, quantity, invoice and settings IDs for read, write, import, reconcile, approve, generate; viewer reads but cannot write; participant sees only own sent documents and own-window quantities (including when another participant held the same point earlier), and gets `403`/`404` on batches; writes on a disabled LEG rejected for non-admins.

### Transfer and backups

Format 8 round-trip of a LEG ZEV (batches, quantities, files, evidence), including source tombstones with their null quantity and message provenance; a format 7 archive imports with defaults; evidence dropped with a warning without the `leg_settlement` section; `CoverageTests` pass.

vZEV and ZEV suites pass unchanged, on SQLite and PostgreSQL.

### Frontend

`npm run lint`, `lint:style`, `check-frontend-hex.mjs`, `test:unit` (document-kind labels, energy-type filtering by `zev_type`, error-code parsing), `build`; keys in four locales. QA in the dev stack: LEG fields hidden on vZEV; import → reconcile → preview → approve flow; both document kinds; no QR on credits; 400px viewport.

### Acceptance criteria

- [ ] ADR written (§1.2).
- [ ] Conformance gate (§6.1): the official SDAT-CH 2025 material, and two independent real deliveries (different VNBs or routes), import, reconcile and match the VNBs' statements. The verified senders and routes are listed in the user guide.
- [ ] Delivery route, receiver EIC-X and member consent confirmed with each of those VNBs.
- [ ] Tax adviser and contract review signed off in writing: who sells to whom (central settlement), the community confirmation text, the dated producer-declaration rule, and the Doc B format (roles, heading, required elements), checked against one sample Doc A and Doc B.
- [ ] Doc A + Doc B per member and period; no netting; no VNB lines; a correction keeps the issued original.
- [ ] Billing cockpit (readiness, period overview, attention) correct for LEG.
- [ ] `ruff`, `check`, `pytest -q` (SQLite + PostgreSQL) and the frontend checks green; user guide chapter written.

---

## 10. Validation register

Section references are to these editions:

| Cited as | Edition | URL |
|---|---|---|
| SDAT-CH Messdatenaustauschprozesse 2025 V2 | 1 Nov 2025, V2 | `https://www.strom.ch/system/files/media/documents/20251204-be-standardisierter-datenaustausch-ch-messdatenaustauschprozesse.pdf` (the short link `media/13628/download` has also served the 2022 edition, which has no LEG chapters) |
| SDAT-CH Hauptdokument 2025 | 4 Dec 2025 | `https://www.strom.ch/de/media/13633/download` |
| SDAT-CH Anhang 3 (Core Components) 2025 | 4 Dec 2025 | `https://www.strom.ch/de/media/13636/download` |
| SDAT-CH Anhang 4 (XML-Schemas) 2025 | 4 Dec 2025 | `https://www.strom.ch/de/media/13631/download` |
| BD LEG 2025 V2 | BD LEG – CH 2025 V2 | `https://www.strom.ch/de/media/15458/download` |

| Claim | Result |
|---|---|
| Legal basis | Validated → StromVG 17d–17e / VV 19e–19h, in force 01.01.2026 ([valfort](https://www.valfort.ch/de/news-insights/energy-law-quarterly-lokale-elektrizit%C3%A4tsgemeinschaften-leg), [17d](https://justement.ch/de/doc/act/ch/734_7/chap_3/sec_2_c/art_17_d), [AS 2025 139](https://www.fedlex.admin.ch/eli/oc/2025/139/de)) |
| Members' relationship + representative | Validated → 17d(5): members regulate their relationship themselves, including supply of self-generated electricity, and appoint a person who represents the community toward the VNB ([17d](https://justement.ch/de/doc/act/ch/734_7/chap_3/sec_2_c/art_17_d)) → `ZevPartyRole` `representative` |
| Internal settlement practice | Validated → central settlement by the LEG/representative, consumption and production settled separately: BKW "verrechnen den Erlös und den Bezug … separat" ([BKW](https://www.bkw.ch/de/strom-in-der-grundversorgung/eigenen-strom-teilen-und-verkaufen/strom-mit-nachbarn-teilen/lokale-elektrizitaetsgemeinschaft/leg-abrechnen-und-verwalten)); WWZ "Verrechnung und Gutschrift des LEG-Stroms liegt bei der LEG selbst" ([WWZ](https://www.wwz.ch/de/privatpersonen/energie/eigenproduktion-eigenverbrauch/leg)); RWB "Verrechnungen und Gutschriften an Produzenten erfolgen durch die Vertretung" ([RWB](https://www.regionalwerke.ch/privat-geschaeftskunden/angebot/eigenverbrauchsgemeinschaften/lokale-elektrizitaetsgemeinschaft-leg)); service provider pays producers and invoices participants ([Regio Energie](https://www.regioenergie.ch/de/leg-/)); producers agree a feed-in price with the LEG, consumers buy from the LEG ([lokalerstrom](https://www.lokalerstrom.ch/betriebsmodelle/leg)) |
| VAT treatment of LEG supplies | Open → no ESTV LEG-specific practice found; an advisory project lists bilateral vs central settlement as the open VAT question ([energonia](https://www.energonia.ch/projekte/leg-und-mehrwertsteuer/)). Nearest practice: ZEV, MWST-Branchen-Info 17 §8.4, adopted 2026-05-26; final text not read, summary and 2025 draft only ([t-r.ch](https://t-r.ch/mwst-zoom-photovoltaik-und-zev-die-neue-mwst-praxis-der-estv-im-ueberblick/), [ESTV draft](https://www.estv.admin.ch/dam/de/sd-web/vdLr6oo8RVQG/mwst-kg-zev-de.pdf)): a producer's sale is taxable if the producer is VAT-registered; the supplier follows from contracts and external appearance → two documents (§4.5.1), no VAT on Doc B in v1, per-producer status + community confirmation (§4.6). The adviser's sign-off, not any ESTV publication cited here, is the authority for the Doc B format |
| Virtual LEG metering point | BKW tells operators to include "den Messtarif für den virtuellen Messpunkt der LEG" on the internal invoice ([BKW](https://www.bkw.ch/de/strom-in-der-grundversorgung/eigenen-strom-teilen-und-verkaufen/strom-mit-nachbarn-teilen/lokale-elektrizitaetsgemeinschaft/leg-abrechnen-und-verwalten)): a VNB charge, passed on as a shared fee. SDAT-CH delivers community totals as `E31` aggregates identified by `CommunityID` ([SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.13), so no virtual-point ID is needed |
| Allocation by the VNB | Validated → consumer shares per VV 19g(4) (minimum of sums, then share); producer shares follow via 19g(6) and VNB practice (WWZ: surplus split proportional to injection, [WWZ](https://www.wwz.ch/-/media/rechtliches/alb/alb-leg.pdf)) → import each member's settled quantity; never recompute or invent a priority |
| ElCom registration no. / LEG ID | No ElCom-issued number ([ElCom](https://www.elcom.admin.ch/en/registration)). **Validated 2026-10-11:** the LEG ID is the SDAT-CH `CommunityID`, assigned by the VNB as six characters of its VSE network identifier, a hyphen and six characters `0-9A-Z`, unique and permanent ([SDAT-CH Hauptdokument 2025](https://www.strom.ch/de/media/13633/download) §4.9) → `leg_community_id`. The data receiver is a market actor with a Swissgrid EIC-X and receiver role `CEM` ([Swissgrid](https://www.swissgrid.ch/en/home/customers/topics/eic/x-codes-ec.html); [SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.12) → `leg_receiver_eic` |
| Manual upload suffices | Not universal → delivery is SDAT-CH ebIX, directly or through a data hub, to a receiver registered with an EIC ([RWB](https://www.regionalwerke.ch/privat-geschaeftskunden/angebot/eigenverbrauchsgemeinschaften/lokale-elektrizitaetsgemeinschaft-leg); [SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.12; channel FTPES per [SDAT-CH Hauptdokument 2025](https://www.strom.ch/de/media/13633/download) §4.13). v1 accepts the files by upload; the route is confirmed per VNB (§6.1) |
| ZEV-in-LEG | Validated possible ([BKW](https://www.bkw.ch/de/strom-in-der-grundversorgung/eigenen-strom-teilen-und-verkaufen/strom-mit-nachbarn-teilen/lokale-elektrizitaetsgemeinschaft)); v1 rejects |
| VNB always bills members | False absolute → collective option Art. 17e(6) ([Swissolar](https://www.swissolar.ch/01_wissen/wirtschaftlichkeit/zev/20241120-be-leg.pdf)); v1 individual billing only, no mode field |
| One area / one VNB | Validated (area + level + municipality + ≤36 kV) |
| Discount 40%/20% | Validated, internal kWh only, VNB-computed |
| SDAT-CH LEG flows | **Validated 2026-10-11** from the standard: `LGZ/EGZ-LEGT` (total), `-LEGR` (residual), `-LEGE` (LEG energy), sent by the VNB (sender `MDR`, `E66`) to receiver role `CEM` with `BusinessReason C40`; products `8716867000030`, `2404050010124`, `2404050010123`; flow from the metering point element; `CommunityID` + `CommunityType` `CT01`/`CT02`; `DocumentFunction` 9/5/1 ([SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.12–§1.13; [Anhang 3](https://www.strom.ch/de/media/13636/download) §4.24, §5.7; [Anhang 4](https://www.strom.ch/de/media/13631/download) §5.2) |
| "Final" flag | **None in SDAT-CH.** Per-value `Condition` (`21` temporary, `56` estimated); plausibilised data by the 5th working day after the month; corrections as `replace` messages where the newest `Creation` applies, until the 3-month clearing deadline ([SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.1.2, §1.2, §1.12) → overridable findings and revisions (§4.3) |
| Positions, DST, splitting, missing values | Validated → positions from `StartDateTime`, 96 per day, 92/100 on DST days, complete days/months only; files split by metering point above 50 MB gzip; zero is never a substitute for a missing value ([SDAT-CH Hauptdokument 2025](https://www.strom.ch/de/media/13633/download) §4.10–§4.12; [SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.2.1) |
| Delivery route, rights, samples | Open → dependencies 1–4 (§6.1): XSD package and any official LEG examples; route, receiver EIC-X and member consent per VNB (members confirm to the representative that it may receive their data, [BD LEG 2025 V2](https://www.strom.ch/de/media/15458/download) §5; receiver registered and authorised, [SDAT-CH Messdatenaustauschprozesse 2025 V2](https://www.strom.ch/de/media/13628/download) §1.12); two independent real deliveries |
| CT01 vs CT02 | Validated → `CT01` "Basis LEG": the community or representative bills members only the local share; `CT02` "Zusammenfassende Rechnung LEG": billed in full ([Anhang 3](https://www.strom.ch/de/media/13636/download) §5.7) → v1 accepts `CT01` only |
| Internal allocation key | Validated → the VNB allocates per member at the same time step even when the LEG agrees another key internally; applying that key is the LEG's business ([BD LEG 2025 V2](https://www.strom.ch/de/media/15458/download) §7.1(3)) → v1 bills the VNB's local shares |
| Licensing of SDAT-CH material | © VSE; commercial use only with consent and payment; copying or distribution beyond the intended recipient's own use is prohibited ([SDAT-CH Hauptdokument 2025](https://www.strom.ch/de/media/13633/download) copyright notice) → no VSE schemas or examples in the repository (§6.1) |
| Issuer/VAT/HKN | Partly resolved → issuer and representative are existing party roles; VAT handled per §4.5.1/§4.6; adviser sign-off still required; HKN not addressed in v1 |
