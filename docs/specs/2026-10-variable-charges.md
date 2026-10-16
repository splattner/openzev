# Feature Spec: One-off and variable charges (#924)

- Spec ID: SPEC-2026-10-variable-charges
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-16
- Target Release: —
- Related Issues: [#924](https://github.com/splattner/openzev/issues/924); related #727 (tariff audience, out of scope), #388 (credits, out of scope), #387 (shared metering points), #465 (shared fee under-recovery)
- Related ADRs: [0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md), [0038](../adr/0038-invoice-generation-lock-order.md)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

A ZEV owner sometimes has costs that are neither energy nor a standing fee: postage for the invoice
run, a one-off repair, a certificate fee. The amount is known only afterwards and differs every
period. Today:

- `SHARED_MONTHLY_FEE` / `SHARED_YEARLY_FEE` and the `MONTHLY_FEE` modes bill a *tariff*: an amount
  set up front, valid for a date range. Billing a one-off cost that way puts it in the tariff list,
  on the participation contract and in the tariff overview PDF, none of which it belongs on.
- A manual line on a draft invoice is lost: `_discard_replaceable_invoices` deletes drafts on
  regeneration and `generate_invoice` rebuilds every item.

**Outcome:** the owner records a **charge** once, says who bears it, and every invoice the charge
falls into carries it as a line item, including after regeneration. A charge is not a tariff: it
has no validity range, no billing mode, no series, and never shows on the contract or the tariff
overview.

### Decisions taken (issue open questions)

| # | Question | Decision |
|---|---|---|
| 1 | Manual-only or derived amounts | Manual amounts only. Per-document fees stay out of scope. |
| 2 | VAT | Explicit per-charge `vat_treatment`: `taxable` or `pass_through`. Never inferred. Amounts are billed as entered in every `vat_mode`; there is **no** inclusive-mode grossing (§4.4). |
| 3 | Period assignment | One `charge_date`. The invoice whose period contains it bills the charge. A late-found cost gets a date in the next period. |
| 4 | Participant with nothing else to bill | The charge still produces a line. `generate_invoices_for_zev` already invoices every participant active in the period, so such a participant gets an invoice consisting of the charge alone. A charge nobody can bear is a readiness warning (§4.5). |
| 5 | Mid-period membership | Bearers are determined on `charge_date` (§4.2). |
| 6 | Rounding | Same rule as shared fees: each share rounded half-up to the centime on its own. A share does not compensate for the others, so an uneven split can recover a centime or two less than the amount (CHF 10.00 over three: 3.33 each, CHF 9.99). This matches `SHARED_MONTHLY_FEE`; see #465. |
| 7 | Category | New `TariffCategory.OTHER` (`"other"`), rendered last on the invoice and PDF. It is not selectable on a tariff (§4.6). |

The issue's three `allocation` values are collapsed to two: `single_participant` is
`selected_participants` with exactly one participant, which gives that participant the whole amount
under either split key.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Data model | `invoices.Charge`, `Charge.participants` (M2M), migration, `TariffCategory.OTHER` |
| Engine | `generate_invoice` adds one `FEE` item per charge borne by the participant |
| VAT | `pass_through` charges stay out of `vat_base_chf` |
| API | `/api/v1/charges/` CRUD, ZEV-scoped; audit events |
| Readiness | A `charges` step on the period readiness payload |
| PDF / public invoice | `other` category group; `flat` unit label |
| Transfer archive | New `charges` section |
| Frontend | Charges page, readiness hint, TypeScript types, i18n (de/fr/it/en) |
| Docs | Baseline spec updates, user-guide chapter |

### Out of scope

- Automatic or per-document fees (postage computed from the number of invoices sent).
- Crediting a participant, negative charges (#388). `amount_chf` must be greater than zero.
- Restricting which participants a *tariff* applies to (#727).
- Recurring charges. Those remain tariffs.
- Editing a charge once an invoice carrying it has been issued; that goes through the correction
  flow (#388, ADR 0037).

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Read and write charges of every ZEV |
| `zev_owner` | Read and write charges of their ZEVs |
| `manager` (ZEV grant) | Read and write charges of the ZEV |
| `viewer` (ZEV grant) | Read only |
| `participant` | 403 on the endpoint (`participant_path = None`). Sees the resulting invoice line like any other line. |
| `guest` | None |

The viewset uses `[IsAuthenticated, HasZevAccess]` and `ZevScopedQuerySetMixin`, as
`TariffViewSet` does. Writes on a disabled ZEV are refused the way tariff writes are
(`tariffs/test_disabled_zev.py`). Frontend route: `ProtectedRoute` with `ZEV_SCOPE`, as `/tariffs`.

## 4. Data model

### 4.1 `Charge` (`invoices/models.py`)

| Field | Type | Constraints / default |
|---|---|---|
| `id` | UUID PK | `default=uuid.uuid4`, not editable |
| `zev` | FK `Zev` | `on_delete=CASCADE`, `related_name="charges"` |
| `description` | CharField(200) | required, non-blank after strip; printed on the invoice |
| `amount_chf` | Decimal(10, 2) | `> 0`; the **total** the ZEV passes on |
| `charge_date` | DateField | required |
| `allocation` | CharField(20) | `ChargeAllocation`: `all_participants` \| `selected_participants`; default `all_participants` |
| `split_key` | CharField(10) | `SplitKey` (`tariffs.models`); default `equal`; ignored when exactly one participant bears the charge |
| `vat_treatment` | CharField(12) | `ChargeVatTreatment`: `taxable` \| `pass_through`; default `taxable`; no inference |
| `participants` | M2M `Participant` | `related_name="charges"`; non-empty iff `allocation == selected_participants`, empty otherwise |
| `created_at` / `updated_at` | DateTime | `auto_now_add` / `auto_now` |

`Meta.ordering = ["-charge_date", "-created_at"]`; index on `(zev, charge_date)`.
`CheckConstraint(amount_chf__gt=0)`.

`Charge.clean()` (called by the serializer's `validate`, since the M2M cannot be validated in
`Model.clean`): `description` stripped and non-empty; every selected participant belongs to
`zev`; the selection is empty for `all_participants` and non-empty for `selected_participants`.

### 4.2 Who bears a charge

`invoices/charges.py::bearers_among(participants, day, allocation, selected_ids)` (in memory) and its
wrappers `bearers_for(zev, day, allocation, selected)` and `charge_bearers(charge)`: participants of
the ZEV whose `[valid_from, valid_to]` contains `charge_date`, intersected with the selection when
`allocation == selected_participants`. Ordered by `pk` for determinism.

Membership is evaluated on `charge_date` alone, never on the invoice period. This is what makes a
single-participant and a batch generation agree: both call the same function, and the shares do not
depend on which other invoices exist (the lesson of `_count_active_participants_by_month`).

Shares come from `split_charge(amount, split_key, bearers)`. For participant *p*, `n` = number of bearers, `Σw` = sum of their `allocation_weight`:

- `split_key == equal` (or `n == 1`): `amount_chf / n`
- `split_key == weight`: `amount_chf × p.allocation_weight / Σw`; a bearer whose weight is 0 gets
  no line (as zero-weight members of a weight-split shared fee).

A share is quantized to `0.01` with `ROUND_HALF_UP`. A share that rounds to `0.00` yields no line.
No bearer (`n == 0`, or `Σw == 0`) yields no line for anybody and is reported by readiness.

### 4.3 Engine integration (`invoices/engine.py`)

`ItemAccumulator` is keyed by tariff (group key, `_tariff_bears_input_vat`, sort order, item type
and description all read the tariff), so charges do **not** go through it. Instead:

1. After `_build_item_payloads(...)`, `generate_invoice` reads
   `generation_context.charge_lines(zev, participant.pk)`: the `ChargeLine(charge, total_chf, shared)`
   entries of charges with `period_start <= charge_date <= period_end` that the participant bears
   (`invoices/charges.py::charge_lines_by_participant`: one charge query with
   `prefetch_related("participants")`, one participants query).
2. `charges_chf = Σ line.total_chf`. `subtotal = subtotal + charges_chf`.
3. `vat_base_chf = subtotal − producer_credit_chf − Σ pass_through lines` (§4.4).
4. `InvoiceItem` rows are created for each line, appended after the tariff items:

| `InvoiceItem` field | Value |
|---|---|
| `item_type` | `FEE` |
| `tariff_category` | `other` |
| `description` | charge description, plus a translated suffix when more than one participant bears it (`charge_shared_marker`: "share of community costs" in de/fr/it/en, mirroring `shared_monthly_*`) |
| `quantity_kwh` | `1` |
| `unit` | `flat` |
| `unit_price_chf` | the share |
| `total_chf` | the share |
| `sort_order` | `CHARGE_SORT_ORDER = 950` (after every `CATEGORY_SORT_ORDER` + type + mode sum); ties fall to `InvoiceItem.Meta.ordering` (description) |

`InvoiceItem` carries no foreign key to `Charge`. An invoice is a finished document (same stance as
`tariff_category` in `zev/transfer/schema.py`): later edits or deletion of the charge never alter
it.

`InvoiceGenerationContext` gains `charge_lines(zev, participant_id)`, which loads every charge of the
period once (`charge_lines_by_participant`) and serves the whole batch from it; the single-invoice
path builds a context of its own and so reads the same data.

### 4.4 VAT

`vat_treatment` decides only the VAT base, and only for `vat_mode == registered`:

| `vat_mode` | `taxable` | `pass_through` |
|---|---|---|
| `registered` | amount in `vat_base_chf`; VAT added on top | amount in `subtotal_chf` and `total_chf`, **not** in `vat_base_chf`; no VAT on it |
| `not_registered` | billed as entered | billed as entered |
| `inclusive` | billed as entered; **not** grossed | billed as entered; **not** grossed |

The `inclusive` rule differs from levies and grid fees on purpose: those are tariff prices stored
net, whereas the owner enters a charge from a receipt, so the figure is already what was paid.
`embedded_vat_chf` is therefore not affected by charges.

`pass_through` corresponds to an expense reimbursement billed in the participant's name and for
their account (Auslagenersatz). Whether a given cost qualifies is a tax question; the application
only records the owner's explicit choice and documents it in the user guide. **Confirm with the
Swiss VAT rules / the owner's tax adviser before release.**

### 4.5 Freezing, regeneration, readiness

**Regeneration.** Charges live outside the invoice, so `_discard_replaceable_invoices` followed by
`generate_invoice` reads them again.

**Freezing without a link.** A charge is *locked* when any of its bearers has an invoice for which
`engine.locked_overlapping_invoices(bearer, charge_date, charge_date)` is non-empty (status past
`draft`, not `cancelled`; the rule regeneration uses). `charges.charge_lock(charge)` answers it for
one charge and `charges.locked_charge_ids(charges)` for a list in two queries. A locked charge refuses `PATCH` and `DELETE` with 409,
`{"code": "charge_locked", "detail", "invoice_number"}`, and a `DENIED` audit event. The same predicate refuses a `POST`/`PATCH` that would create a charge
for a date with a locked bearer invoice (400 on `charge_date`, message naming the invoice number
and telling the owner to pick a date in a later period). This guarantees a charge is never
silently missing from an issued invoice, and that shares are never half-issued.

**Stale drafts.** A draft is created before a charge is added and approved without it unless
regenerated. `compute_readiness` therefore gains a `charges` step:

| Condition | `StepResult` |
|---|---|
| No charge dated in the period | `done`, count 0 |
| Every charge in the period has bearers and no bearer's draft is older than the charge's `updated_at` | `done`, count = charges |
| At least one bearer's draft invoice for the period has `created_at < charge.updated_at` | `todo`, `detail_data = {"stale_drafts": N}`, link to the invoice list |
| A charge in the period has no bearer | `warn`, `detail_data = {"unbilled_charges": [descriptions]}` |

Bearers of a locked charge are, by definition, not drafts, so a locked charge never produces
`todo`. The step is added in `_bulk_period_readiness` (`BulkData.charges` and `BulkData.drafts`,
loaded in `_load_bulk`: one query for the charges in the span, one for draft invoices only when
there are charges), between `generated` and `approved`: `_select_next_action` returns the first
`todo`/`warn` step, and stale drafts must be regenerated before they are approved.
`NEXT_ACTION_BY_STEP["charges"] = "generate"` reuses the existing action, so no new frontend
next-action value is needed (it is also what a `warn` step points at; the warning text carries the
meaning).

### 4.6 `TariffCategory.OTHER`

`tariffs/models.py::TariffCategory` gains `OTHER = "other", "Other"`. Consequences, all of which
must be handled because unknown categories are silently dropped by the PDF grouping:

- `Tariff.category` must not accept `other`: `Tariff.clean()` rejects it (the choices stay on the
  field, since `InvoiceItem.tariff_category` shares the enum). The tariff serializer exposes only
  the four tariff categories in its schema documentation.
- `invoices/pdf.py::_group_items_by_category`: `other` is in `labels` and `ordered_categories`
  (last). New keys in `pdf_translations.py::INVOICE_TRANSLATIONS`: `cat_other` (de "Weitere Kosten",
  fr "Autres frais", it "Altri costi", en "Other charges") and `unit_flat` ("pauschal" / "forfait" /
  "forfait" / "flat"), the label of `unit == "flat"`.
- `CATEGORY_SORT_ORDER` is left untouched (charges use `CHARGE_SORT_ORDER`).
- `invoices/views_public.py` passes `tariff_category` through as a value; `financial_summary.py` only
  labels the column. `tariff_overview.py` labels tariff categories only, so charges never reach it.
- Frontend: `Tariff['category']` stays four values; `InvoiceItem['tariff_category']` and the
  invoice presentation get a fifth (§7).

Migrations: `tariffs/0020_variable_charges` altering the `choices` of `Tariff.category`;
`invoices/0026_variable_charges` creating `Charge` and altering the `InvoiceItem.tariff_category`
choices. No data
migration. Rollback: drop the `Charge` table; invoices that carry an `other` line keep it as a
plain value.

## 5. API contracts

All under `/api/v1/invoices/`, registered in `invoices/urls.py` (`router.register("charges", ...)`),
viewset `invoices/views_charges.py::ChargeViewSet(AuditedCreateDestroyMixin, AuditedUpdateMixin,
ZevScopedQuerySetMixin, ModelViewSet)`, `zev_lookup = "zev"`, `participant_path = None`,
`scope_parent_path = ("zev",)`.

| Method & path | Behaviour |
|---|---|
| `GET /charges/` | ZEV-scoped, paginated list; `is_locked` for the whole page is computed in two queries. Filters: `zev_id` (scoping mixin), `period_start` / `period_end` (charge date within), `participant` (charges for everyone plus those naming that participant). |
| `POST /charges/` | Create. 400 on validation errors (§4.1, §4.5). |
| `GET /charges/{id}/` | Detail. |
| `PATCH /charges/{id}/` | Update; 409 `charge_locked` when locked. |
| `DELETE /charges/{id}/` | Delete; 409 `charge_locked` when locked. Drafts that carried the line keep it until regenerated. |
| `POST /charges/preview/` | Read-only, nothing saved. Takes the create payload, validates it exactly like a create (a date an issued invoice covers is refused) and answers `{"bearers": [{"participant", "name", "share_chf"}], "total_billed_chf", "unrecovered_chf"}` for the dialog's "who pays what" table, using §4.2 and §4.3 unchanged. |

Validation order in `ChargeSerializer.validate`: the caller must manage the ZEV (before anything
names an invoice or participant of it), participants belong to the ZEV, participants are set only for
`selected_participants`, then the lock check on the date. `ChargeSerializer` fields: `id`, `zev`, `description`, `amount_chf`, `charge_date`, `allocation`,
`split_key`, `vat_treatment`, `participants` (list of participant ids; write), `is_locked`
(read-only), `created_at`, `updated_at`. `zev` is writable only on create and must be one the user
can access.

Audit (`AuditActionCategory.INVOICE`): `charge.create`, `charge.update` (with the field diff),
`charge.delete`, and `charge.update_denied` / `charge.delete_denied` (status `denied`, locked). The
target display is the description; metadata carries `zev_id` and `charge_date`.

## 6. Async and integration behavior

No new task. `generate_invoices_for_zev` and `generate_invoice` are unchanged except for the charge
step; failures stay isolated per participant (ADR 0011). A charge inside the generation lock window
is covered by the participant row lock already taken by `generate_invoice` (ADR 0038): a concurrent
`PATCH` that would lock-check a bearer takes the same `Participant` rows `FOR UPDATE` in `pk`
order, so a charge cannot change between the lock check and the invoice write.

**Transfer archive.** New section `charges` (`SECTION_CHARGES`, file `charges.json`), ordered after
`tariffs`, depending on `participants`. Row: `{"id", <CHARGE_FIELDS>, "participant_ids": [...]}`,
`CHARGE_FIELDS = (description, amount_chf, charge_date, allocation, split_key, vat_treatment)`.
`FORMAT_VERSION` 7 → 8 (7 and older stay readable; they simply lack the section). The importer
(`_import_charges`) maps `participant_ids` through the archive-id map, drops unknown ids with a
warning, and reports a `selected_participants` charge left with no bearer as an error, which rejects
the import as any section error does. Invoices stay independent of charges, so the invoices section
keeps its `("participants",)` dependency.

**Backups** (`2026-09-backup-and-restore.md`): `backups/registry.py` gets a `charges` section
(`ZevPart("invoices.Charge", "zev")`, after `participants`); Django's serialization carries the
`participants` many-to-many inline. `backups.test_archive.CoverageTests` enforces that every model is
registered or excluded.

**MCP server** (`2026-09-mcp-server.md`): unchanged. Charges are not exposed; `explain_invoice`
already explains `FEE` lines from their description.

## 7. Frontend

### 7.1 `ChargesPage` (`frontend/src/pages/ChargesPage.tsx`)

Route `/charges` (lazy-loaded in `AppRoutes.tsx` beside `tariffs`, `ProtectedRoute
allowedRoles={ZEV_SCOPE}`), linked from the same navigation group as Tariffs; follows
`2026-04-frontend-management-page-design.md` (DataTable, one primary action, `ActionMenu` for the
row, `FormModal`).

- List: date, description, amount, bearers ("All participants" / "3 participants" / the single
  name), VAT treatment, a lock badge when `is_locked`.
- Filter tabs by period (reusing `PeriodSelector`).
- Create/edit dialog: description, amount, date, "Who pays": *All participants* | *Selected
  participants*; participant multi-select when selected; split key (hidden for exactly one
  participant); VAT treatment with an explanatory hint. The live "who pays what" table comes from
  the `preview` data and warns when a bearer would be missing, when the date falls in a locked
  period, and about the centime remainder.
- Locked charges: edit and delete actions disabled with a tooltip pointing to the correction
  flow.

### 7.2 Readiness and invoice cockpit

`BillingPeriodCard` / the readiness step list render the new `charges` step: `todo` links to the
period's invoice list with the text "N draft invoices predate a charge change. Regenerate them."
and `warn` names the unbilled charges. Keys `readiness.steps.charges.*` in all four locales.

### 7.3 Invoice presentation

`InvoicePresentation` and the invoice detail group lines by `tariff_category`; add the `other`
group (label `invoice.categories.other`), and the `flat` unit label. No hardcoded text; keys added
to `frontend/src/i18n/locales/{de,fr,it,en}`.

### TypeScript types (`frontend/src/types/api.ts`)

```ts
export type InvoiceItemCategory = 'energy' | 'grid_fees' | 'levies' | 'metering' | 'other'

export interface Charge {
  id: string
  zev: string
  description: string
  amount_chf: string
  charge_date: string
  allocation: 'all_participants' | 'selected_participants'
  split_key: 'equal' | 'weight'
  vat_treatment: 'taxable' | 'pass_through'
  participants: string[]
  is_locked: boolean
  created_at: string
  updated_at: string
}

export interface ChargePreview {
  bearers: { participant: string; name: string; share_chf: string }[]
  total_billed_chf: string
  unrecovered_chf: string
}
```

`InvoiceItem.tariff_category` (api.ts:1321) widens to `InvoiceItemCategory`; `Tariff['category']`
stays the four values. `ReadinessStep` key union gains `'charges'`.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| New category silently dropped from the PDF (`_group_items_by_category` ignores unknown categories) | Explicit `other` entry plus a test that fails if a `TariffCategory` value has no PDF group |
| Draft approved without a charge added after generation | Readiness `charges` step, `todo` on stale drafts (§4.5) |
| Wrong VAT treatment chosen by the owner | Explicit choice, no default inference beyond `taxable`, hint text in the dialog, user-guide explanation; tax review before release |
| Shared amount under-recovered by up to `n/2` centimes | Documented and shown in the dialog; identical to shared fees (#465) |
| Membership changes after the charge was entered change the shares | Bearers are computed at generation time from `charge_date`; the preview and the invoice use the same function; issued invoices are frozen |
| Archive round-trip loses charges | `charges` section, tested round-trip |

## 9. Test plan

### Backend — `invoices/test_charges.py` (new)

- Bearers: all participants; selected; participant joining after / leaving before `charge_date`
  excluded; single participant gets the whole amount under either split key.
- Shares: equal, weight, zero-weight member skipped, rounding leaves CHF 9.99 on 10.00 over three,
  no bearer yields no line.
- Engine: line appears with `FEE` / `other` / `flat`; regeneration keeps it; a charge dated outside
  the period is not billed; single `generate_invoice` equals the batch run; a participant with no
  consumption gets an invoice holding only the charge.
- VAT: `registered` + `taxable` adds VAT; `pass_through` excluded from `vat_base_chf`;
  `not_registered` and `inclusive` bill as entered with `embedded_vat_chf` unchanged.
- Freeze: `PATCH`/`DELETE` of a locked charge → 409; create for a date with a locked bearer invoice →
  400; editing the charge after issue never changes the issued invoice.
- API: ZEV scoping, role matrix (owner/manager/participant/guest), disabled ZEV writes refused,
  audit events written, `preview` matches the engine.
- Readiness: stale draft → `todo`; no bearer → `warn`; clean → `done`.
- `tariffs/tests.py`: `Tariff` rejects category `other`.
- PDF: `other` group rendered last with `flat` label in all four languages; guard test over all
  `TariffCategory` values.
- `zev/test_transfer*.py`: charges export/import round-trip with participant links.

### Frontend

- Unit tests for the charge form schema (selected participants required, amount > 0) and the
  preview table.
- Invoice presentation renders the `other` group.
- i18n key parity across the four locales (existing check).

### Manual verification

Dev stack: create a shared charge, generate, confirm the line on the PDF, add a second charge,
see the readiness hint, regenerate, approve, confirm the charge is locked. Check a ~400px
viewport.

### Acceptance criteria

1. A charge recorded once appears on every bearer's invoice for the period containing its date,
   and again after any regeneration.
2. Shares follow §4.2 and match between single and batch generation.
3. `pass_through` never enters `vat_base_chf`.
4. An issued invoice can no longer be affected by editing or deleting the charge.
5. The invoice PDF, public invoice page and annual statements show the charge under its own group.
6. A whole-ZEV archive round-trips charges.
7. `ruff check .`, `python manage.py check`, `python -m pytest -q`, `npm run lint`,
   `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`,
   `npm run build` pass, and `mkdocs build --strict` passes with the new user-guide chapter.
