# Feature Spec: Tariff overview PDF

- Spec ID: SPEC-2026-tariff-overview-pdf
- Status: Draft
- Scope: Minor
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-05
- Target Release: 1.10.0
- Related Issues: [#566](https://github.com/splattner/openzev/issues/566)
- Related ADRs: —
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

A ZEV's tariffs exist only as rows on the Tariffs page, behind a login. Every
other piece of participant-facing data a ZEV produces has a printable form —
invoice, annual statement, financial summary, participation contract — and the
prices do not.

That matters in four recurring situations: a participants' meeting where prices
are the thing people ask about; a price change that has to be communicated
after an Art. 7b import; the archive, where a ZEV should be able to state what
its prices were on a given date; and a participant checking a bill, for whom
the contract covers only *local* energy tariffs and nothing else.

**Outcome of this iteration:** a ZEV owner clicks one button on the Tariffs page
and gets a PDF listing every tariff in force on a chosen date, grouped by
category, with each price band named exactly as the contract and the invoice
name it, and the ZEV's VAT treatment stated on the face of the document.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — context | `invoices/tariff_overview.py`: tariffs → grouped display rows |
| Backend — wording | `invoices/tariff_overview_translations.py`: de/fr/it/en |
| Backend — template | `templates/invoices/tariff_overview_pdf.html`, on `pdf/shared_pdf_base.html` |
| Backend — API | `GET /api/v1/invoices/invoices/tariff-overview/` |
| Backend — shared helper | `band_recurrence()` in `invoices/band_labels.py`; `display_grid_base_chf_per_kwh()` in `invoices/tariff_pricing.py`, adopted by the contract |
| Frontend | Download button in `TariffToolbar`, wired to the page's existing validity filter |
| Docs | `docs/user-guide/07-tariff-configuration.md` |

### Out of scope

- **No model changes and no migration.** Everything the document prints is
  already stored.
- **Participant access.** The `/tariffs` route is `admin | zev_owner` only, so
  there is no UI a participant could reach this from, and the participation
  contract already states the tariffs a participant signed up to. Opening the
  endpoint would mean a Reports-page card as well; see §10.
- **Customisable `PdfTemplate`.** The financial summary is not customisable
  either. Adding it means a sample-context builder, preview endpoint and admin
  card; see §10.
- **A per-kWh summary line** totalling the components a grid consumer pays. It
  is the most comparable number on the page but is separable; see §10.
- **Price history.** The Tariffs page has a history chart; reproducing it in
  print is a separate document.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Any ZEV, by naming `zev_id` |
| `zev_owner` | Own ZEVs only, by naming `zev_id` |
| `participant` | None (403) |
| `guest` | None (401) |

**Backend:** `permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]`, plus
`_get_authorised_zev()` from `views_reports.py`, which already returns 403 for
another owner's ZEV and 404 for an unknown or malformed id.

**Frontend:** the button lives inside `TariffsPage`, already wrapped in
`<ProtectedRoute allowedRoles={['admin', 'zev_owner']}>`
(`frontend/src/App.tsx:170`).

## 4. Data model

**No changes.** The document is a projection of `Tariff` and `TariffPeriod` as
they stand.

### 4.1 In-memory display shapes

Built by `invoices/tariff_overview.py`; never serialised over the API.

**`TariffRow`** — one tariff (one series version).

| Key | Type | Notes |
|---|---|---|
| `name` | `str` | `Tariff.name` |
| `validity` | `str` | `"01.01.2026 – 31.12.2026"`, or `tr["valid_open"]` formatted with `valid_from` |
| `billing_mode_label` | `str` | Localised `BillingMode` label, from this document's own translations |
| `is_current` | `bool` | In force on `as_of`. Always `True` when `scope="valid"` |
| `notes` | `str` | `Tariff.notes`, printed as a muted line when non-empty |
| `price_rows` | `list[PriceRow]` | At least one; a tariff that would produce none is skipped |

**`PriceRow`** — one printed price line under a tariff.

| Key | Type | Notes |
|---|---|---|
| `label` | `str` | `band_description(period, tr)`, or the fee/percentage wording |
| `recurrence` | `str` | `band_recurrence(period, tr)`; `""` when unrestricted |
| `amount` | `str` | Already formatted to the unit's precision |
| `unit` | `str` | `"Rp./kWh"`, `"CHF/Mt."`, `"CHF/Jahr"`, `"%"` |
| `footnote` | `str \| None` | Marker key into the footnote list, e.g. `"multiband_base"` |

**`CategoryGroup`**

| Key | Type | Notes |
|---|---|---|
| `key` | `TariffCategory` | |
| `label` | `str` | Reused from `INVOICE_TRANSLATIONS` so the overview and the invoice name categories identically |
| `tariffs` | `list[TariffRow]` | |

## 5. Selection and ordering

```python
def _select_tariffs(zev, as_of: date, scope: str) -> list[Tariff]
```

- Base queryset: `zev.tariffs.prefetch_related("periods")`.
- `scope="valid"` (default): `valid_from <= as_of` and (`valid_to` is null or
  `valid_to >= as_of`). This is the same predicate as
  `contract_pdf._active()`.
- `scope="all"`: every tariff, with `is_current` computed per row.
- Ordering: category in the invoice's canonical order (`ENERGY`, `GRID_FEES`,
  `LEVIES`, `METERING` — matching `pdf._group_items_by_category`), then
  `name`, then `-valid_from` so the newest version of a series leads.
- Categories with no tariffs are omitted entirely, not printed empty.

Bands within a tariff keep `TariffPeriod.Meta.ordering` (period type, then
start time, then id), which is what makes a multi-band tariff read down the day.

## 6. Price rendering by billing mode

| `billing_mode` | Rows produced | Unit | Precision |
|---|---|---|---|
| `energy` | One per `TariffPeriod` | `Rp./kWh` | 2 dp (`price × 100`) |
| `percentage_of_energy` | One | `Rp./kWh`, or `%` when no grid base exists | 2 dp |
| `monthly_fee` | One | `CHF/Mt.` | 2 dp |
| `yearly_fee` | One | `CHF/Jahr` | 2 dp |
| `per_metering_point_monthly_fee` | One | `CHF/Mt.` | 2 dp, label names *per metering point* |
| `per_metering_point_yearly_fee` | One | `CHF/Jahr` | 2 dp, same |
| `shared_monthly_fee` | One | `CHF/Mt.` | 2 dp, label names the split key |
| `shared_yearly_fee` | One | `CHF/Jahr` | 2 dp, same |

**Rappen, not CHF/kWh.** `Rp./kWh` is the convention on the participation
contract (`tr["tariff_rp_unit"]`) and on every Swiss tariff sheet. Printing
five decimals of CHF/kWh — the invoice's precision, which it needs because it
multiplies by kWh — reads as noise on a document meant for comparison.

**Shared fees name their denominator.** For `SHARED_*`, `fixed_price_chf` is
what the *community* pays, divided across participants active in the billed
month. The row label states that and names the `split_key` (headcount or
weight), otherwise the printed number reads as a per-participant amount and is
wrong by the size of the ZEV.

### 6.1 Percentage-of-energy tariffs

The contract derives its grid base as flat → HT → `periods[0]`
(`backend/invoices/contract_pdf.py:62-71`).
The engine's `_price_energy` instead sums `_get_tariff_price(t, ts)` over the
active grid tariffs, resolved per reading timestamp. On a single-band grid
tariff the two agree; on a multi-band one they do not.

The overview must not add a third answer:

1. Extract `display_grid_base_chf_per_kwh(grid_tariffs)` into
   `invoices/tariff_pricing.py`, lifted verbatim from `contract_pdf`.
2. `contract_pdf._build_local_tariff_display` calls it instead of computing
   inline. Behaviour unchanged — this is a move, and the existing contract
   tests are the regression net.
3. The overview calls the same function.

The engine is *not* refactored onto it. It resolves a price per timestamp
because it has to; a static display figure is a different question with a
different right answer. Where a grid tariff contributing to the base has more
than one band, the row carries the `multiband_base` footnote:

> The base price shown is the tariff in force outside time-band restrictions.
> The effective price follows the band that applies at the time of consumption.

Row wording, matching the contract:

```
18.00 % × 29.50 Rp./kWh        5.31   Rp./kWh
```

With no active grid tariff the amount degrades to `18.00` with unit `%`, as
the contract already does.

## 7. VAT

`Zev.vat_mode` (`backend/zev/models.py:114`) decides
what the printed prices mean, and the document must say so. Under `inclusive`
the stored prices are **net** and the invoice grosses them per line at render
time, so the tariff table's number is deliberately not the number on the bill.

| `vat_mode` | Meta band | Footnote |
|---|---|---|
| `not_registered` | "Nicht MWST-pflichtig" | none |
| `registered` | "MWST-pflichtig" + `vat_number` | "Alle Preise exkl. MWST." |
| `inclusive` | "MWST inklusive" | "Preise netto. Auf der Rechnung wird die MWST aufgeschlagen." |

The footnote is unconditional for the two registered modes. A tariff document
handed to participants that silently omits it is the one way this feature does
harm.

## 8. Layout

Template: `backend/templates/invoices/tariff_overview_pdf.html`, opening with
`{% include "pdf/shared_pdf_base.html" %}` — the first *new* document on that
base (the financial summary predates it and keeps its own styles). From it the
overview inherits `document-header`, `.brand-mark`, `.eyebrow`,
`.document-status`, and the running `.page-meta` furniture.

```
                                                  TARIFÜBERSICHT
● ZEV Sonnenhof                                       01.01.2026
  Anna Muster, Dorfstrasse 12, 8000 Zürich       [ GÜLTIG AM … ]
════════════════════════════════════════════════════════════▂▂

ERSTELLT AM        TARIFE        MWST
05.09.2026         7             Inklusive (Preise netto)

┌─────────┬──────────────────────────────┬─────────┬──────────┐
│         │ Solarstrom ZEV               │         │          │
│ Energie │   Nach Energie · ab 01.01.26 │         │          │
│         │   Hochtarif      Mo–Fr 07–20 │   22.50 │ Rp./kWh  │
│(rowspan)│   Niedertarif    übrige Zeit │   18.00 │ Rp./kWh  │
│         ├──────────────────────────────┼─────────┼──────────┤
│         │ Netzstrom · Einheitstarif    │   29.50 │ Rp./kWh  │
├─────────┼──────────────────────────────┼─────────┼──────────┤
│ Abgaben │ Netzzuschlag                 │         │          │
│         │   18.00 % × 29.50 Rp./kWh ¹  │    5.31 │ Rp./kWh  │
├─────────┼──────────────────────────────┼─────────┼──────────┤
│ Messung │ Zählermiete · pro Monat      │    8.00 │ CHF/Mt.  │
└─────────┴──────────────────────────────┴─────────┴──────────┘

¹ Der gezeigte Basispreis …
```

| Element | Detail |
|---|---|
| Document label | `tr["document_label"]` — "TARIFÜBERSICHT" |
| Document number | The `as_of` date in `.document-number` style: light 22 pt with the year in `<strong>`, matching the invoice number's prefix/suffix split |
| Status chip | `.document-status` — "Gültig am 05.09.2026", or "Alle Versionen" under `scope="all"` |
| Meta band | Three `.eyebrow`-labelled cells: generated-on, tariff count, VAT mode |
| Category column | `rowspan` label cell, the same construction as the invoice's `.category-label-cell` (`backend/templates/invoices/invoice_pdf.html:786`) |
| Tariff row | Name in `600` weight; second line, muted 7.5 pt: billing mode · validity |
| Band rows | Indented under the tariff; label left, recurrence in muted text right of it, amount right-aligned `tabular-nums` |
| Superseded rows | `scope="all"` only — `--muted` ink, validity span in place of "ab" |
| Footnotes | Numbered, below the table, only those actually referenced |
| Page furniture | Running footer: ZEV name · document label · as-of date · `N / M` |
| `@page` | A4, the invoice's margins; no QR reservation, no named pages |

The table breaks across pages with `thead` repeating and
`tbody.tariff-group { break-inside: avoid }`, so a tariff's bands never split
from their name.

## 9. API contracts

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/invoices/invoices/tariff-overview/` | GET | `IsAuthenticated`, `IsZevOwnerOrAdmin` | Returns `application/pdf` |

**View:** `TariffOverviewView(APIView)` in
`invoices/views_reports.py`, routed
in `invoices/urls.py` ahead of `router.urls` alongside the other report paths.

**Query parameters**

| Name | Required | Default | Validation |
|---|---|---|---|
| `zev_id` | yes | — | 400 when absent; 404 when unknown or malformed (`_get_authorised_zev`) |
| `as_of` | no | today | `date.fromisoformat`; 400 with `"as_of must be YYYY-MM-DD."` |
| `scope` | no | `valid` | One of `valid`, `all`; 400 otherwise |

**Responses**

| Status | When |
|---|---|
| 200 | `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="tariff-overview-<as_of>.pdf"` |
| 400 | Missing `zev_id`, unparseable `as_of`, unknown `scope` |
| 401 | Anonymous |
| 403 | An owner naming another owner's ZEV |
| 404 | Unknown or malformed `zev_id` |

A ZEV with no tariffs in scope renders successfully with an empty-state line
rather than 404 — "no tariffs are configured" is a true and useful statement
about a ZEV, and a 404 would be indistinguishable from a bad id.

Reuses `_pdf_response(..., disposition="attachment")`.

## 10. Deferred decisions

| Decision | Taken | Revisit when |
|---|---|---|
| Participant access | Excluded — no reachable UI, contract covers their own tariffs | A participant-facing tariff view is asked for; would need a Reports-page card |
| Customisable `PdfTemplate` | No — consistent with the financial summary | An operator asks to rebrand it |
| Per-kWh summary total | No | After the first version ships; it is the number people compare and deserves its own thought |
| Audit event | No — annual statements and financial summaries are not audited either | Report downloads become auditable as a class |

## 11. Frontend

### 11.1 TariffToolbar

**File:** `frontend/src/features/tariffs/TariffToolbar.tsx`

- New optional prop `onDownloadOverview?: () => void` and `overviewBusy: boolean`.
- Renders a `button-secondary` with `faFilePdf`, labelled
  `pages.tariffs.overviewPdf.action`, between the import and create buttons.
- Present only when `onDownloadOverview` is passed — the same convention the
  import button already uses for "no single ZEV selected"
  (`frontend/src/pages/TariffsPage.tsx:240`).
- While busy, disabled and labelled `pages.tariffs.overviewPdf.busy`.

### 11.2 TariffsPage

**File:** `frontend/src/pages/TariffsPage.tsx`

- `useMutation` over `downloadTariffOverview`, `onSuccess` → `downloadBlob`.
- Passes `scope` from the page's existing `validityFilter`, whose values are
  already `'valid' | 'all'` — so the PDF shows what the operator is looking at,
  and the filter needs no mapping.
- `as_of` is not sent; the backend defaults to today. A date picker is a later
  addition and would go next to the validity filter.
- On failure, `pushToast` with the existing error handling used by the import
  flow.

### API client functions

**File:** `frontend/src/lib/api/invoices.ts`

| Function | Method | Endpoint |
|---|---|---|
| `downloadTariffOverview()` | GET | `/invoices/invoices/tariff-overview/` |

```typescript
export async function downloadTariffOverview(params: {
  zev_id: string
  scope?: 'valid' | 'all'
  as_of?: string
}): Promise<Blob> {
  const { data } = await api.get('/invoices/invoices/tariff-overview/', {
    params,
    responseType: 'blob',
  })
  return data as Blob
}
```

No TanStack Query key: this is a download, not cached state.

### i18n

`pages.tariffs.overviewPdf.{action,busy,error,filename}` in all four locales
(`frontend/src/i18n/locales/{de,fr,it,en}.ts`). The existing dead-key guard
test covers them.

## 12. Backend translations

**File:** `invoices/tariff_overview_translations.py` —
`TARIFF_OVERVIEW_TRANSLATIONS: dict[str, dict]` keyed `de` / `fr` / `it` / `en`,
selected by `zev.invoice_language` with a German fallback, exactly as
`FINANCIAL_SUMMARY_TRANSLATIONS`.

Keys: `document_label`, `valid_at`, `all_versions`, `generated_on`,
`tariff_count`, `vat_label`, `vat_not_registered`, `vat_registered`,
`vat_inclusive`, `vat_note_registered`, `vat_note_inclusive`, `valid_open`,
`valid_span`, `no_tariffs`, `unit_rp`, `unit_chf_month`, `unit_chf_year`,
`unit_percent`, `fee_per_metering_point`, `fee_shared_equal`,
`fee_shared_weight`, `footnote_multiband_base`, `page_of`, and
`billing_modes` (a sub-dict over every `BillingMode` value, mirroring the
frontend's `billingModes` block).

Category labels are **not** duplicated here — they are read from
`INVOICE_TRANSLATIONS` so the overview and the invoice cannot drift.

### New shared band vocabulary

**File:** `invoices/band_labels.py`

```python
def band_recurrence(period, tr: dict) -> str:
    """``Mo–Fr, 07:00–20:00``. Empty when the band is unrestricted."""
```

Weekdays collapse into contiguous runs the way `month_ranges` collapses months,
and are omitted when the band covers all seven. Hours are omitted when
`time_from`/`time_to` are unset. Both blank yields `""`, and the template then
prints nothing rather than an empty parenthesis.

Requires three new keys in `CONTRACT_TRANSLATIONS` (its docstring already says
the band vocabulary lives there because the contract needed it first):
`tariff_weekdays_short` (a 7-element list, Monday first),
`tariff_weekday_range` (`"{first}–{last}"`), `tariff_recurrence_join`
(`"{days}, {hours}"`). The existing
`ContractPdfTranslationParityTests.test_all_locales_have_identical_keys_and_structure`
enforces them across all four locales.

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Net prices printed without a VAT note under `inclusive` mode | High — participants compare against a bill and conclude they were overcharged | Footnote is unconditional; a test asserts the string is present in the rendered text |
| Overview, contract and invoice name the same band differently | Medium — three documents describing one tariff in three vocabularies | All three go through `band_description()`; a test renders a contract and an overview for the same tariff and compares the labels |
| Percentage base disagrees with the contract | Medium | One extracted helper, called by both; the engine's per-timestamp resolution is documented as deliberate and footnoted |
| A ZEV with many tariffs produces an unreadably long table | Low | `break-inside: avoid` per tariff group and a repeating `thead`; no page cap |
| Shared fee read as a per-participant amount | Medium — off by the size of the ZEV | Row label states the split and names the `split_key` |
| Lifting the grid-base helper changes contract output | Low | Verbatim move; existing contract tests are the net |

## 14. Test plan

### Backend — `backend/invoices/test_tariff_overview.py`

**`TariffOverviewAccessTests`** (7 tests):

| Test | Asserts |
|---|---|
| `test_owner_downloads_own_zev` | 200, `Content-Type: application/pdf` |
| `test_admin_downloads_any_zev` | 200 for a ZEV the admin does not own |
| `test_owner_cannot_read_another_owners_zev` | 403 |
| `test_participant_is_refused` | 403 |
| `test_anonymous_is_rejected` | 401 |
| `test_zev_id_is_required` | 400 |
| `test_malformed_zev_id_is_404` | 404, not a 500 from the UUID field |

**`TariffOverviewParameterTests`** (5 tests):

| Test | Asserts |
|---|---|
| `test_as_of_defaults_to_today` | A tariff starting tomorrow is absent |
| `test_as_of_selects_the_version_in_force` | The 2025 version's price appears for `as_of=2025-06-01`, the 2026 one does not |
| `test_unparseable_as_of_is_400` | Error message names the expected format |
| `test_scope_all_includes_superseded_versions` | Both versions' prices in the text |
| `test_unknown_scope_is_400` | |

**`TariffOverviewContentTests`** (9 tests, via `PdfReader.extract_text()`):

| Test | Asserts |
|---|---|
| `test_categories_appear_in_invoice_order` | Energy before grid fees before levies before metering |
| `test_empty_category_is_omitted` | A category with no tariffs prints no header |
| `test_every_band_of_a_multi_band_tariff_is_listed` | Three bands → three prices, none averaged |
| `test_band_labels_match_the_contract` | Same tariff rendered into both documents yields the same band label strings |
| `test_seasonal_band_carries_its_season` | `Hochtarif (Okt–Mär)` |
| `test_prices_are_printed_in_rappen` | `22.50`, not `0.22500` |
| `test_shared_fee_names_its_split` | Split wording and `split_key` present |
| `test_percentage_row_matches_the_contract_figure` | Identical effective price in both documents |
| `test_multiband_grid_base_adds_the_footnote` | Footnote text present; absent for a single-band base |

**`TariffOverviewVatTests`** (3 tests):

| Test | Asserts |
|---|---|
| `test_inclusive_states_prices_are_net` | Net-price footnote present |
| `test_registered_states_prices_exclude_vat` | Excl.-VAT footnote and the VAT number |
| `test_not_registered_has_no_vat_footnote` | Neither footnote |

**`TariffOverviewEdgeTests`** (3 tests):

| Test | Asserts |
|---|---|
| `test_zev_without_tariffs_renders_an_empty_state` | 200 and the empty-state string, not 404 |
| `test_energy_tariff_without_periods_is_skipped` | No blank row, no crash |
| `test_output_is_pdfa` | XMP identification present, as `test_pdfa.py` checks |

**`TariffOverviewTranslationParityTests`** (1 test): all four locales carry
identical keys and identical `billing_modes` subkeys, mirroring
`ContractPdfTranslationParityTests`.

**Regression:** `backend/invoices/test_contract_context.py` must pass unchanged
after the grid-base helper is lifted out — that is the assertion that the move
was verbatim.

### Frontend — `frontend/tests/tariff-overview.test.ts` (3 tests)

The download itself is browser plumbing; what is worth testing is the pure
mapping. `tariffOverviewParams(zevId, validityFilter)` returns `scope: 'valid'`
and `scope: 'all'` for the two filter values, and the filename helper produces
`tariff-overview-<date>.pdf`.

- Build and type checks: `npm run build`

### Acceptance criteria

- [ ] An owner downloads a tariff overview from the Tariffs page in one click
- [ ] The PDF lists every tariff in force today, grouped by category in the
      invoice's order, with one row per price band
- [ ] Band labels are byte-identical to the participation contract's for the
      same tariff
- [ ] A percentage-of-energy tariff prints the same effective price as the
      contract
- [ ] The ZEV's VAT treatment is stated on the document, and under `inclusive`
      the prices are explicitly marked net
- [ ] Switching the page's validity filter to "all" produces a PDF including
      superseded versions
- [ ] The document is PDF/A-3b and visually a sibling of the invoice
- [ ] No migration is required

## 15. Open questions

- **Does `as_of` need a picker?** The validity filter already answers "current
  or everything", and an arbitrary historical date is a rarer need than it
  sounds. The endpoint takes the parameter from day one, so a picker is a
  frontend-only addition if it turns out to be wanted.
- **Should the empty-state PDF exist at all**, or should the button be disabled
  when the ZEV has no tariffs? Rendering it is more honest for an archive
  ("on this date, none were configured") and costs one template branch.
