# Feature Spec: VSE/AES tariff import (Art. 7b StromVV)

- Spec ID: SPEC-2026-vse-tariff-import
- Status: Completed
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-09-02
- Target Release: 1.8.0
- Related Issues: [#507](https://github.com/splattner/openzev/issues/507)
- Related ADRs: —
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

Since 2025, Art. 7b StromVV obliges every Swiss grid operator (VNB/DSO) to
publish its grid-usage, energy, metering and public-authority tariffs
machine-readably by 31 August each year, at a single freely accessible
internet address. The format is defined in NNMV-CH 2025 Annex 10 and published
as an OpenAPI 3.0.3 document.

Those are exactly the numbers a ZEV needs. Today every one of them is typed in
by hand on the Tariffs page each year, transcribed from a PDF — slow, and a
wrong grid fee propagates into every invoice the engine produces.

**Outcome of this iteration:** a ZEV owner enters the operator's URL once, sees
every tariff the document would create for their ZEV — with its price, its
status against what already exists, and everything that could not be
represented — ticks the ones that apply, and gets them created as normal
`Tariff` + `TariffPeriod` records. Next year's document appends new versions to
the same series.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Backend — parsing | `tariffs/importers/vse_json.py`: document → tariff candidates, defensively |
| Backend — planning | `tariffs/importers/planner.py`: candidate status against the ZEV's existing tariffs; the write path |
| Backend — fetching | `tariffs/importers/remote.py`: HTTP fetch with SSRF, size and timeout guards |
| Backend — API | `POST /api/v1/tariffs/imports/vse/preview/` and `.../apply/` |
| Model | `Zev.tariff_source_url` |
| Frontend | Import wizard on the Tariffs page; tariff URL field in ZEV settings |
| Audit | One `AuditEvent` per apply, category `import` |

### Out of scope

- **File upload** of the document. Iteration 1 is URL-only; the parser takes a
  decoded payload, so adding upload is a view-layer change.
- **Power/demand charges** (#529), **dynamic tariffs** (#530), reactive-power
  charges and storage refunds — reported, never imported.
- Any scheduled or automatic refresh. The import is manual, previewed and
  user-confirmed.
- Publishing tariffs *as* a VNB. OpenZEV is a consumer of this standard.

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Preview and import into any ZEV |
| `zev_owner` | Preview and import into ZEVs they own |
| `participant` | None — 403 |
| `guest` | None — 401 |

Both endpoints use `permission_classes = [IsAuthenticated, IsZevOwnerOrAdmin]`.
`IsZevOwnerOrAdmin` checks the *role* only, so ownership is checked explicitly
in `tariffs.views_import._resolve_zev`: a non-admin whose `id` is not the ZEV's
`owner_id` gets `PermissionDenied`. Without that check any ZEV owner could
write tariffs into any other ZEV.

## 4. Data model

No new models. Tariffs are created through the existing `Tariff` /
`TariffPeriod` pair, so imported tariffs are ordinary tariffs: editable,
versionable, deletable, and priced by the engine with no special-casing.

### 4.1 Zev — new field

**Model:** `zev.models.Zev`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `tariff_source_url` | `URLField(max_length=500)` | `""` | blank; where this operator publishes its machine-readable tariffs |

Stored per ZEV rather than in `AppSettings`: there is no central registry, each
operator hosts its own address, and one deployment serves ZEVs on different
operators. Added to `ZEV_FIELDS` in `zev/transfer/schema.py`, so it survives a
ZEV export/import round-trip.

Migration: `zev/migrations/0021_zev_tariff_source_url.py`.

### 4.2 Candidate (in-memory only)

`tariffs.importers.vse_json.Candidate` — one OpenZEV tariff the import *would*
create. Never persisted; it carries the status, warnings and provenance that
only exist while the user is deciding.

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | `f"{name}@{valid_from}"` — the same pair that decides idempotency, so it survives a preview/apply round-trip |
| `name`, `category`, `billing_mode`, `energy_type` | `str` | What the created `Tariff` would carry |
| `fixed_price_chf` | `Decimal \| None` | Fee candidates only |
| `valid_from`, `valid_to` | `date` | From the document's `startDate` / `endDate` |
| `periods` | `list[ProposedPeriod]` | Energy candidates only |
| `source_component` | `str` | `base` or `energy` — which published price this candidate came from. Persisted on the created `Tariff` |
| `source_series_name` | `str` | The operator's own name for the component's series, before the suffix. Persisted alongside `source_component` |
| `source_tariff_name`, `source_tariff_type`, `source_customer_type`, `source_voltage_level`, `standard_basegroup` | | Provenance, shown in the preview only |
| `billing_mode_options` | `tuple[str, ...]` | Modes the user may pick instead; empty when there is nothing to choose |
| `warnings` | `list[str]` | Lossy mappings — importable |
| `blocked_reason` | `str \| None` | Set when the entry cannot be represented at all |

`recommended` is `standard_basegroup and is_importable and not is_free`.

## 5. Mapping

### 5.1 Tariff type → category

| Standard `tariffType` | OpenZEV | Note |
|---|---|---|
| `electricity` | `category=energy`, `energy_type=grid` | The DSO's supply is *grid* energy from the ZEV's point of view — the community buys it through its connection, not from its own roof |
| `grid` | `category=grid_fees` | |
| `metering` | `category=metering` | |
| `regional_fees` | `category=levies` | |
| `municipalityTaxes[]`, `cantonalTaxes[]` | `category=levies` | Own tariffs regardless of the parent entry's type |

### 5.2 Prices → billing modes

One standard entry becomes **two** OpenZEV tariffs when it carries both a base
and an energy price, because `Tariff` has a single `billing_mode` and
`SERIES_FIELDS` forbids two same-named tariffs from disagreeing on it.

| Standard | OpenZEV | Name |
|---|---|---|
| `prices.base` (`CHF/M`) | `fixed_price_chf` + a monthly fee mode the user picks (below) | `"<tariffName> (Grundpreis)"` |
| `prices.energy[]` (`CHF/kWh`) | `billing_mode=energy` + `TariffPeriod` rows | `"<tariffName> (Arbeitspreis)"` |

The component suffix is applied **even when only one component is present**. A
document that grows a base price next year must append to the same series
rather than fork it under a bare name. These strings become invoice line
labels, hence the Swiss-German billing vocabulary.

The suffix is **presentation, not identity**. Which component a tariff came
from is recorded structurally on `Tariff.source_component`, with the
operator's own pre-suffix name in `source_series_name`. Both are written by
the importer and read-only on the API — a client that could set them could
fake a series match. Together they let §8 match a series through a rename on
either side, which a derived name cannot: it is the same tariff whatever
anyone has since called it. Tariffs entered by hand leave both blank.

**The billing mode for a base price is the user's choice, not a guess.** The
document says the price is CHF per month; it cannot say *who* pays it. So a
fee candidate carries `billing_mode_options` and the preview renders a picker
on that row:

| Mode | When it is right |
|---|---|
| `shared_monthly_fee` *(default)* | Classic ZEV: the operator bills the community once for its connection, and the fee is split across participants |
| `monthly_fee` | vZEV whose participants each hold their own DSO contract |
| `per_metering_point_monthly_fee` | A per-meter charge — the Messtarif is one |

Only the *monthly* modes are offered. The yearly modes read `fixed_price_chf`
as a per-year amount, so offering one for a `CHF/M` price would bill a twelfth
of it. The default leads with `shared_monthly_fee` because billing a
connection fee per participant collects it N times over, which is the more
damaging of the two mistakes.

`Candidate.billing_mode_options` is the single allowlist: the frontend renders
exactly that list and `planner._with_chosen_billing_mode` accepts exactly that
list, so a mode can never appear in the picker that the write path would then
refuse — nor be reached by a client that never saw the picker. An override on
an energy candidate (which offers nothing) is **refused, not ignored**:
silently billing per kWh what somebody asked to be billed monthly is precisely
what this feature must not do.

`split_key` is left at the model default (`equal`) for the shared modes;
splitting by weight instead is an edit after import.

### 5.3 Time bands → `TariffPeriod`

`PeriodType` offers exactly three slots — `flat`, `high`, `low` — so what
decides whether an entry fits is the number of **distinct prices**, not the
number of windows.

Bands are first grouped by the months they apply in, and the question is then
answered **per season** — `period_type` only has to tell apart bands competing
for the same moment, and a winter band never competes with a summer one. A
document pricing winter-HT, winter-NT, summer-HT and summer-NT therefore fits,
carrying four distinct prices overall but two per season.

| Distinct prices in one season | Result |
|---|---|
| 1 | One `flat` period, `time_from`/`time_to` `NULL`, however many windows it was written across |
| 2 | Higher price → `high`, lower → `low`; one row per window, so a price split across two windows (evening + night) gets two `low` rows |
| ≥ 3 | One unnamed `band` per window (#528). The HT/NT heuristic below does not apply: there is no pair to guess at, so nothing is assumed and nothing is warned about |

Imported bands never carry a `label`. The standard does not name its bands, so
inventing one would be worse than showing the window it published.

Each period carries its season in `TariffPeriod.months`; a band covering all
twelve months stores blank, which is what the engine already reads as "every
month", so a non-seasonal import is byte-for-byte what it was before seasons
existed. Month groups that *overlap* rather than partition the year are refused:
grouping is by exact month set, so two groups sharing months would be mapped as
if they never competed. A year only partly priced is imported with a warning —
the engine's in-season fallback covers the rest, but at a price the document
never meant for it.

The document this was built against writes three windows — day, evening,
night — with two prices, and maps cleanly onto HT/NT. The standard does not
label its bands, so the higher-price-is-HT heuristic is stated as a warning on
the candidate rather than applied silently.

Other band handling:

- `from == to == "00:00"` is the standard's constant marker → one `flat` period.
- `to == "23:59"` is the standard's end-of-day spelling and is treated as
  24:00 for coverage purposes, then written back as `23:59`. Because the engine
  matches `time_from <= t < time_to`, the last minute of the day is nominally
  unmatched; readings are 15-minute or hourly, so no reading ever falls there,
  and one that did would fall back to the tariff's first period.
- A window written backwards (`22:00`–`06:00`) wraps past midnight and is split
  into two rows. One row spanning midnight would match nothing at all.
- `weekdays` map to `TariffPeriod.weekdays` (`"0,1,…"`, Mon–Sun). All seven is
  stored as blank, which is what the engine already reads as "every day".
- Hours no band covers produce a warning naming the effect: they bill at the
  tariff's first band, which is what the engine's fallback does.

### 5.4 Precision

`price_chf_per_kwh` is `Decimal(8,5)` and `fixed_price_chf` is `Decimal(10,2)`.
Published prices like `0.0802` fit; anything longer is rounded `ROUND_HALF_UP`
**and the candidate says so**. Prices are net of VAT on both sides, so
OpenZEV's own VAT handling applies unchanged.

## 6. Constructs that are reported, not imported

Every one of these produces a candidate with a `blocked_reason`, shown in the
preview and refused by the apply step even if its key is sent. Nothing is ever
silently dropped.

| Construct | Reason given | Tracked |
|---|---|---|
| Two month groups that overlap | Which group prices the shared months is ambiguous | — |
| `tariffForm: dynamic` | The price lives in an external time series; the URL is named in the message | #530 |
| Energy price not in `CHF/kWh` | Cannot be billed per kWh | — |
| Base price not in `CHF/M` | Does not map to a monthly fee | — |
| Negative price | The standard requires prices ≥ 0 | — |

Non-blocking, reported as warnings on the candidate: a non-zero
`prices.power` (CHF/kW — OpenZEV has no demand billing mode; tracked in #529,
which also notes that demand *is* derivable from the 15-minute readings already
stored), a non-zero `prices.reactivePower`, and a non-zero
`prices.refundStorage`. Components published as `0.00` — of which real
documents carry many — produce no warning, but a candidate whose only price is
zero is never pre-selected.

## 7. Defensive parsing

The OpenAPI definition is normative — NNMV-CH Annex 10 says so itself — but
the annex's own example has already drifted from it, which predicts what
published documents look like. The parser validates against the OpenAPI shape
and accepts the drifted spellings:

| | Annex example | OpenAPI v1.0.1 | Parser |
|---|---|---|---|
| Dates | `"01.01.2025"` | `2025-01-01` | Both |
| `base` | bare `5.52` | `{price, priceUnit}` | Both |
| Weekdays | `mo`/`tu`, `ed` = all days | `"Mo"`/`"Tu"` | Case-insensitive, `ed` understood |
| Months | | `"Jan"`… | Case-insensitive |

Failure granularity:

- Whole-document problems (not an object, no `tariffs` array, no entries) raise
  `TariffDocumentError` → HTTP 400 with the message.
- A single unreadable **entry** lands in `ParsedDocument.errors` and the rest
  are still offered. A malformed entry for a customer group this ZEV does not
  use must not cost it the one it does.
- A single unmappable **component** becomes a blocked candidate, so the reason
  is attached to the thing it is about.
- Two candidates resolving to the same `key` — the standard says `tariffName`
  is unique per DSO, but a published document is not obliged to be correct —
  keep the first and report the second.

## 8. Planning against existing tariffs

`planner.plan_import(zev_id, document)` gives every candidate a status and a
sentence. This is where a careless import doubles somebody's bill, so the same
planning code runs **again inside the write transaction** against freshly read
rows.

**Which series a candidate belongs to** is resolved before any of this, by
`planner._resolve_series`:

1. **Provenance**, when the candidate has one: tariffs whose
   `(source_series_name, source_component)` match. A tariff imported from the
   same published component is the same series however it has been renamed
   since — by us, or by the operator in the new document. The versions of a
   series share a name, so the one already in use wins, and the created
   version takes it rather than the name the document derives
   (`PlannedCandidate.series_name`, echoed to the preview so a row says where
   it is going).
2. **Name**, otherwise. Tariffs entered by hand carry no provenance, and
   neither does anything imported before it was recorded, so the name has to
   keep working.

Provenance is the more specific of the two, so a hand-made tariff that happens
to be called what the document proposes is not captured by a renamed series.

Before this, the derived name was the only link back to the published
component, and renaming a series silently forked a second one from the next
import — leaving both live and billing at once.

| Status | Meaning | Applied? |
|---|---|---|
| `new` | No tariff of that series in this ZEV | yes |
| `new_version` | The series exists with a different `valid_from`; the predecessor is closed the day before, and the new version's end date is capped by any later version (`series.plan_new_version`) | yes |
| `duplicate` | A version already starts on that date — the document has been imported before | no |
| `conflict` | The name exists but disagrees on `category` / `energy_type`, or on a `billing_mode` this candidate cannot be imported as — all of which `Tariff.clean` would reject | no |
| `unsupported` | `blocked_reason` set by the parser | no |

**A `billing_mode` mismatch is matched to the series, not refused.** The
document does not record which of `FEE_BILLING_MODE_OPTIONS` a fee was
imported as — that answer is the user's (§5.2) — so next year's document
proposes the default again and disagrees with the choice already made. Since
`SERIES_FIELDS` includes `billing_mode`, that used to plan as `conflict`,
which the preview renders unselectable; and because the wizard disables a
row's billing-mode picker along with its checkbox, the one control that could
have resolved it was disabled too. The plan therefore takes the mode the
series already uses, provided it is in this candidate's
`billing_mode_options`, and says so in `detail`. A mode the candidate cannot
be imported as — an energy candidate offers none — stays a `conflict`.

This applies only where the user has *not* answered: an explicit
`selections[].billing_mode` that disagrees with the series is reported rather
than overruled (`_plan_one(..., billing_mode_was_chosen=True)`). Matching a
question nobody answered is a convenience; overruling an answer would be the
silent mis-billing §5.2 exists to prevent.

**Idempotency** falls out of `duplicate`: re-importing the same document
creates nothing, changes nothing, and does not trip the same-name overlap
guard. **Next year's document** falls out of `new_version`: the standard always
carries an `endDate`, so versions close cleanly, and a hand-entered open-ended
predecessor is truncated rather than colliding.

Each candidate is written inside its own `transaction.atomic()` savepoint, so a
document that fails on one customer group still delivers the tariffs the ZEV
actually uses.

Every created tariff's `notes` carry the operator name and number, the
published tariff name and type, the customer group, the operator's own comment,
and `Source: <url> (imported <date>)`.

## 9. API contracts

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/tariffs/imports/vse/preview/` | POST | `IsAuthenticated, IsZevOwnerOrAdmin` + ownership | Fetch, parse, plan. Writes nothing. |
| `/api/v1/tariffs/imports/vse/apply/` | POST | same | Re-fetch, verify digest, create the selected candidates |

Both are declared in `tariffs/urls.py` **before** `router.urls` so the viewset
detail routes cannot shadow them.

**Preview request** — `VseTariffImportPreviewRequestSerializer`:

```json
{ "zev": "<uuid>", "url": "https://…/tarife.json" }
```

`url` is optional; omitted, the ZEV's stored `tariff_source_url` is used, and
a ZEV with neither gets a 400 saying so.

**Preview response** — `VseTariffImportPreviewSerializer`: `dso_name`,
`dso_number`, `source_url`, `document_digest`, `candidates[]`
(`VseTariffCandidateSerializer`, including `status`, `detail`, `warnings`,
`recommended`, `effective_valid_to`), `errors[]` (`{tariff, error}`).

**Apply request** — `VseTariffImportApplyRequestSerializer`:

```json
{ "zev": "<uuid>", "url": "…",
  "selections": [{ "key": "<key>", "billing_mode": "monthly_fee" }, …],
  "document_digest": "<sha256 hex>", "remember_url": true }
```

Only keys and the billing mode chosen for each travel back — never tariff
data. The server re-fetches and re-parses the document, so nothing a client
sends can become a price. `billing_mode` is optional; omitted, the candidate's
proposed mode is used, and the frontend omits it whenever the user left the
row alone. `document_digest` is what ties the confirmation to the version the
user reviewed: a mismatch is **409 Conflict**, not a partial write.

A candidate whose chosen mode changes its `billing_mode` may plan differently
from the preview — a series will `conflict` on a mode other than its own,
because `SERIES_FIELDS` includes `billing_mode` and an explicit choice is not
silently matched to the series the way an omitted one is (§8). That is
caught by the re-plan inside the write path and reported in `skipped`.

`remember_url` (default `true`) stores the URL on the ZEV so next year's
refresh is one click.

**Apply response** — `VseTariffImportResultSerializer`: `created[]`
(`{name, category, billing_mode, valid_from, valid_to}` — the mode is echoed
so the result confirms what was chosen), `skipped[]` (`{name, reason}`),
`errors[]` (`{name, error}`). 201 when anything was created, else 200.

**Errors:** `TariffFetchError` and `TariffDocumentError` become 400 with the
message in `detail` — a bad URL is a user-correctable mistake, not a 500.

## 10. Fetch safety

`tariffs/importers/remote.py`. The URL is necessarily user-supplied, so the
fetch is a server-side request to an attacker-influenceable address.

| Guard | Value |
|---|---|
| Schemes | `http`, `https` only. Several operators still publish over plain http; the document is public either way |
| Address | The host is resolved and every address checked with `ipaddress`: not `is_global`, or multicast, is refused |
| Redirects | `_ValidatingRedirectHandler` re-runs the address check on **every hop**, max 5. A public URL that 302s to `169.254.169.254` would otherwise walk straight past the first check |
| Size | 5 MB, checked against `Content-Length` *and* against what actually arrived (`read(MAX + 1)`) |
| Timeout | 20 s |

Resolution here and connection later leaves a small TOCTOU window; closing it
fully means connecting to a pinned address with a `Host` header, which urllib
does not make easy. The deployment's egress rules are the second layer, and
this is noted in the module docstring.

The digest returned is `sha256` of the exact bytes received.

**What a failure is allowed to say.** A blocked request that names the address
it blocked is still an answer: aim the import at an internal hostname, read the
resolution off the error, and the guard above has been walked around without
being defeated. So `TariffFetchError` carries two strings — the message
returned to the user, which is either a literal or built from what the user
typed, and `log_detail`, which holds the resolved address, the socket or TLS
error, and the operator server's own reason phrase. `views_import._fetch_failed`
logs the second and returns the first. Concretely:

| Situation | Returned | Logged |
|---|---|---|
| Resolves into private space | "`<host>` does not resolve to a public address…" | the address it resolved to |
| DNS failure | "The host `<host>` could not be resolved…" | the `gaierror` |
| Transport failure | "The document could not be downloaded…" | exception type and message |
| Operator returned an error | "…answered HTTP 403." | status *and* reason phrase, plus the URL |
| Not JSON | "…is not valid JSON. Check that the link points at…" | the `JSONDecodeError` |

`TariffDocumentError` needs no such split: every message it carries is a
literal.

## 11. Audit

One event per apply, via `audit.services.record_audit_event`:

- `action_category`: `import`; `action_type`: `tariff.import_vse`
- `target_type`: `zev.Zev`, `zev` set, so it appears in the ZEV's scoped stream
- `metadata_json`: `source_url`, `document_digest`, `dso_name`, `dso_number`,
  `selected`, `created` (`{name, billing_mode}` each), `skipped`, `errors`

`metering.ImportLog` was **not** reused. Its name and fields (`rows_total`,
`rows_imported`, `rows_skipped`) lean toward meter readings, it lives in the
metering app, and the Imports page lists it as metering history — an entry with
no rows in it would be noise there. The audit stream already answers who, when
and from where. (Answers open question 1 of #507.)

## 12. Frontend

### 12.1 Tariffs page

**File:** `frontend/src/pages/TariffsPage.tsx`

`TariffToolbar` gains an optional `onOpenImportModal`; the button renders only
when a single ZEV is selected, since an import needs one target. The modal
receives `selectedZev.tariff_source_url` as its initial URL.

### 12.2 Import wizard

**File:** `frontend/src/features/tariffs/VseTariffImportModal.tsx`

Three steps in one `FormModal` (`maxWidth="1000px"`):

1. **URL** — prefilled from the ZEV, with a line explaining Art. 7b.
2. **Preview** — operator name and source URL; a banner listing any entries the
   document itself got wrong; then one `.data-table` per tariff category with a
   checkbox, the proposed name (plus the operator's customer-group text, a
   `Standard` badge for `standard_basegroup`, and every warning inline), the
   price (fee, or one line per band with its window), the validity window, and
   a status badge with its explanation. Non-applicable rows are disabled.
   "Select standard tariffs" / "Clear selection", and a "remember this address"
   checkbox.
3. **Result** — created, skipped and failed, then Close.

Mutations: `previewVseTariffImport`, `applyVseTariffImport`. Success invalidates
through `invalidateTariffQueries(queryClient, zevId)`. Neither response is
cached — a preview is a point-in-time read of an external document.

**File:** `frontend/src/features/tariffs/vseImportSelection.ts` —
`isSelectable`, `recommendedKeys`, `defaultBillingModes`, `selectionFor`,
`toggleKey`, `trimPrice`. Extracted from the component so the rules that decide
what gets written are testable.

The chosen modes live in their own `Record<string, string>` beside the tick
`Set`, so "clear selection" and "select standard tariffs" do not throw away a
billing decision the user already made.

A row whose `series_name` differs from its `name` shows
`import.addedToSeries` under the name — the column states what the document
proposes, so the row has to say which existing series it would actually join.

### 12.3 ZEV settings

**File:** `frontend/src/components/ZevGeneralSettingsFields.tsx` — a
full-width `tariff_source_url` input in the Grid Connection section, with a
hint. Also carried by `lib/zevForm.ts` (default `''` and the mapper).

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
interface VseTariffPeriodPreview {
    period_type: 'flat' | 'high' | 'low'
    price_chf_per_kwh: string
    time_from: string | null
    time_to: string | null
    weekdays: string
}

type VseTariffCandidateStatus = 'new' | 'new_version' | 'duplicate' | 'conflict' | 'unsupported'

interface VseTariffCandidate {
    key: string
    name: string
    category: 'energy' | 'grid_fees' | 'levies' | 'metering'
    billing_mode: string
    billing_mode_options: string[]
    energy_type: string | null
    fixed_price_chf: string | null
    valid_from: string
    valid_to: string | null
    notes: string
    periods: VseTariffPeriodPreview[]
    source_tariff_name: string
    source_tariff_type: string
    source_customer_type: string
    source_voltage_level: number | null
    standard_basegroup: boolean
    /** Where the row lands; differs from `name` for a renamed series (§8). */
    series_name: string
    status: VseTariffCandidateStatus
    detail: string
    warnings: string[]
    recommended: boolean
    effective_valid_to: string | null
}

interface VseTariffImportPreview {
    dso_name: string
    dso_number: number | null
    source_url: string
    document_digest: string
    candidates: VseTariffCandidate[]
    errors: Array<{ tariff: string; error: string }>
}

interface VseTariffImportSelection {
    key: string
    billing_mode?: string
}

interface VseTariffImportResult {
    created: Array<{
        name: string; category: string; billing_mode: string
        valid_from: string; valid_to: string | null
    }>
    skipped: Array<{ name: string; reason: string }>
    errors: Array<{ name: string; error: string }>
}
```

`Zev` and `ZevInput` gain `tariff_source_url?: string`.

### API client functions

**File:** `frontend/src/lib/api/tariffs.ts`

| Function | Method | Endpoint |
|---|---|---|
| `previewVseTariffImport()` | POST | `/tariffs/imports/vse/preview/` |
| `applyVseTariffImport()` | POST | `/tariffs/imports/vse/apply/` |

### i18n

`pages.tariffs.import.*` (action, title, intro, url, load, statuses, columns,
result, messages, errors) and `pages.zevSettings.fields.tariffSourceUrl` /
`tariffSourceUrlHint`, in all four locales.

## 13. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A wrong price silently reprices every invoice | High | Nothing is written without a per-candidate preview; the engine mapping is tested end to end against a real document |
| The base-fee billing mode is wrong for this ZEV | Medium | Chosen per row in the preview from a three-option picker (§5.2), not assumed |
| The HT/NT assignment is a heuristic | Medium | Stated as a warning on the candidate rather than applied silently |
| SSRF through the user-supplied URL | High | Address check on the URL and every redirect hop; scheme allowlist; size and timeout caps (§10) |
| The document changes between preview and apply | Medium | `document_digest` → 409 |
| Re-import creates duplicates or trips the overlap guard | High | `duplicate` status; planning re-run inside the write transaction |
| A published document drifts from the OpenAPI shape | Medium | Defensive parsing (§7); per-entry failure |
| Preview lets an authenticated user make the server fetch arbitrary public URLs | Low | Role- and ownership-gated, public addresses only, 5 MB / 20 s caps. Not rate-limited yet — worth adding if the endpoint is ever exposed more widely |
| A refused fetch describes the deployment's network back to the user | Medium | Resolved addresses and raw socket errors are logged, never returned (§10) |

## 14. Test plan

### Backend — `backend/tariffs/test_vse_import.py` (72 tests)

The suite leans on a **real published document** — InfraWerke Münsingen's 2027
tariffs, fetched from the operator's own website and checked in unchanged as
`backend/tariffs/testdata/vse_tariffs_iwm_2027.json` (23 published entries → 35
candidates) — with synthetic documents for the shapes it happens not to
contain.

**`RealDocumentTests`** (7): every published entry is understood with no
errors; only the three `standardBasegroup` candidates are pre-selected; a
base+energy entry becomes two tariffs; the three-window/two-price entry maps
onto HT + two NT rows; a municipal surcharge becomes its own levy; power and
reactive charges are reported; zero-priced components are offered but never
recommended.

**`DefensiveParsingTests`** (8): dotted dates; a bare-number `base`;
case-insensitive weekday and month codes; a midnight-wrapping window split in
two; one bad entry not blocking the rest; a document with no `tariffs` array
and a bare JSON array both rejected outright; duplicate names reported.

**`SeasonalPriceTests`** (9): a two-season flat tariff becomes one band per
season; four distinct prices fit when they are two per season; a year-round band
stores no months at all; overlapping month groups are refused rather than
guessed; a year only partly priced is imported but flagged; the HT/NT heuristic
is reported per season, naming each season's own pair; three prices become
unnamed bands rather than being refused, carry no HT/NT guess, while two prices
still become HT and NT.

**`UnsupportedConstructTests`** (5): dynamic tariffs (with the URL in the
message), a wrong energy unit, a wrong base unit and a negative price each
blocked with a reason; excess precision rounded with a warning.

**`PlanningTests`** (10): a new name; re-importing the same document changes
nothing; next year's document appends a version and closes the previous one; an
open-ended predecessor is truncated; a name meaning something else is a
conflict; only selected candidates are created; a blocked candidate is refused
even when its key is sent; two versions inside one document chained rather than
collided; a stale key is an error; the source URL is on every imported tariff's
notes.

**`BillingModeChoiceTests`** (7): a fee offers exactly the three monthly modes
and defaults to the shared one; no yearly mode is ever offered (it would bill a
twelfth of a CHF/M price); an energy candidate offers none; a picked mode is
what gets created, including the per-metering-point case the shared default
gets wrong; a mode that was never offered is refused; an override on an energy
candidate is refused rather than ignored.

**`EnginePricingTests`** (3): the imported multilevel tariff is read back by
`invoices.engine._get_tariff_price` — daytime at HT, night and evening at NT,
and the boundaries at 06:59/07:00 and 20:59/21:00.

**`RemoteFetchTests`** (10): a literal private address and `localhost` both
refused *with the guard's own message* (a connection error would otherwise let
the test pass with the guard gone); non-http schemes; a redirect into private
space; an oversized body with no `Content-Length`; an HTML page instead of JSON;
the digest covering the downloaded bytes. Three more cover what a failure is
allowed to say: the refusal does not report what the name resolved to (while
`log_detail` does), a TLS error's paths do not reach the response, and the
operator's own reason phrase is not echoed back.

**`ImportEndpointTests`** (13): auth; participants forbidden; an owner refused
another owner's ZEV; preview writes nothing; the stored URL as fallback; a ZEV
with no URL told what is missing; a fetch failure as a 400 not a 500; apply
creates only what was ticked and remembers the URL; the audit event and its
metadata; a changed document refused with 409 and no write; `remember_url:
false` honoured; the preview publishes the billing modes it may offer, and a
mode picked there reaches the created tariff.

Each of these was checked to fail with the production code reverted (duplicate
detection, wrap-around splitting, the address checks, the billing-mode
allowlist, and the message/log split were each disabled in turn).

### Frontend — `frontend/tests/vse-tariff-import.test.ts` (12 tests)

Selection rules (`isSelectable` for all five statuses, `recommendedKeys`
skipping a recommended-but-inapplicable candidate, `toggleKey`), billing-mode
state (`defaultBillingModes`; `selectionFor` omitting the mode when the row was
left alone and sending it when it was changed), price trimming, and the two API
call shapes — including that apply sends only selections and a digest.

- `npm run test:unit`, `npm run build`, `tsc --noEmit`, `eslint`, `stylelint`
- Locale parity is enforced by the existing `tests/locale-parity.test.ts`

### Acceptance criteria

- [x] A valid VSE/AES tariff JSON can be imported from a URL
- [ ] …and from an uploaded file *(deferred — see §2)*
- [x] The user sees a preview of every parsed tariff and selects which apply
- [x] Selected entries create `Tariff` + `TariffPeriod` records that price
      correctly through the existing billing engine
- [x] Unrepresentable constructs are reported per entry with a reason and never
      silently dropped
- [x] Where the document cannot say how a fee should be billed, the preview
      asks instead of assuming
- [x] Re-importing the same document is idempotent and does not trip the
      same-name overlap guard
- [x] Next year's document appends a new version, leaving prior versions closed
- [x] Import is audited (who, when, source URL, what was created/skipped)
- [x] Only admin / ZEV owner can import; URL fetch is size- and timeout-limited
- [x] Backend tests cover the mapping table and each gap case

## 15. Open questions

1. **Naming convention.** `"(Grundpreis)"` / `"(Arbeitspreis)"` become invoice
   line labels and are German in a four-language product. Renaming a whole
   series after import is one action (`rename-series`), so this is a default
   rather than a commitment — but it is a default that ships.
2. **The fee billing-mode default.** Resolved by making it a per-row choice in
   the preview (§5.2). What remains open is only the *default*:
   `shared_monthly_fee` is right for a classic ZEV and wrong for a vZEV, and
   `Zev.zev_type` already knows which this is. Keying the default off it would
   save a click; it would also make the picker's initial value depend on a
   setting the user is not looking at, which is why it is not done yet.
3. **The remaining gaps are tracked separately**, each naming the code that
   blocks it: power/demand billing #529 and dynamic tariffs #530. Seasonal
   prices (#527) and multi-band tariffs (#528) are now supported — see
   `2026-03-tariffs-and-billing-engine.md` §3.2b and §3.2c. Seasonal prices (#527) are now supported — see
   `2026-03-tariffs-and-billing-engine.md` §3.2b. #530 is blocked on something
   outside this repo, since the standard defines `prices.dynamic` as a bare URL
   with no response schema.
