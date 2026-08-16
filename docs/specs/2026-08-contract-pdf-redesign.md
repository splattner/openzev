# Baseline Spec: Contract PDF Redesign

- Spec ID: SPEC-2026-08-contract-pdf-redesign
- Status: Approved
- Scope: Minor
- Type: Change
- Owners: spalinger
- Created: 2026-08-10
- Target Release: post-1.7.0
- Related Issues: none
- Related ADRs: none
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

The participation contract PDF (a legally signed document) previously used a
legacy flat stylesheet with hardcoded colors, manually repeated per-page
headers, no footer and no page numbers, and rendered several system-known
values (owner address, participation start, active VAT rate) as blank fill-in
lines. The invoice PDF already had a modern design system (CSS design tokens,
single page-1 document header, running page furniture).

This change ports the invoice's design system and page machinery into the
contract, extracts the shared parts into one partial so both documents stay
visually consistent long-term, and pre-fills every value the system knows.
The contract now prints page numbers (`Seite N von M`), a document id and
issue date in the running footer, a non-binding summary appendix
(`Anhang A`) with the legal information blocks, and a **binding privacy
notice (`Anhang B`)** (see §7).

Because the contract is a legally signed instrument, the clause-wording
updates described in §2 and §7 are called out explicitly rather than shipped
as visual polish; they should receive a human legal review (Swiss EnG/EnV,
FADP) before release.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Templates | New shared partial `pdf/shared_pdf_base.html`; `invoices/invoice_pdf.html` refactored to include it (CSS extraction only — markup untouched); `contracts/participant_contract_pdf.html` fully redesigned to the same anatomy |
| Context | `invoices/dates.py` (shared date formatting), `_build_contract_context` additions (formatted contract date, participation start, document id, VAT rate display), `build_sample_contract_context` extended |
| Tests | `invoices/test_contract_context.py` extended with context-field, translation-parity, tariff-rule and end-to-end render tests; `invoices/test_template_admin.py` extended with override-integrity tests (save-time validation, staleness) |
| Template admin | `PdfTemplate` overrides are validated before they are stored (PATCH rejects syntax errors and unknown output variables with `400`), and customizations are stale-tracked via `PdfTemplate.default_digest` + `is_stale` (migration `invoices/0009`, admin UI stale banner) — see §5.2 |
| Docs | This baseline spec |
| Legal wording | Clause texts were updated alongside the layout (see §7): clauses 2 (purpose/scope with EnG/EnV citations), 4 (mandate + annual information duty), 5 (binding tariff rule, cap with tenancy-law reservation, notification/termination, billing), 6 (per-interval allocation, feed-in remuneration), 7 (universal-service guarantee), 8 (grid-operator-area join condition), 10 (communication) and 12 (regulatory-change dissolution). `Anhang B` adds a **binding** privacy notice (controller, purposes, recipients, retention table, data-subject rights) |

### Out of scope

- No new API endpoints or permission changes; the download endpoint keeps its
  path, method and permission model.
- Contract download button unchanged. The admin template editor
  (`AdminPdfTemplatesPage.tsx`) gains an override-staleness banner,
  accessible tab roles (roving tabindex + arrow-key navigation) and the
  redesigned contract template's fields in the editor reference, as part of
  the template-validation work.
- Only one data-model addition: `PdfTemplate.default_digest` (migration
  `invoices/0009`) for stale-override detection; `PATCH` now validates
  overrides before storing (see §5.2).
- The contract download flow adds no audit events (the document id is printed
  on the PDF, not audit-logged). Template-admin mutations keep their audit
  trail; non-admin attempts are DENIED-logged by the shared
  `_AdminTemplateView` base (`views_templates.py`).
- Customized `PdfTemplate` DB overrides for the contract keep rendering their
  stored standalone HTML and are **not** migrated — the redesign only reaches
  them after a reset to default (DELETE on the template endpoint).
- The plain-language summary page is reworded into the non-binding
  `Anhang A`; the legally binding wording changes are in scope above.

## 3. Actors, permissions, and ZEV scope

Unchanged from the invoice lifecycle spec (§5.7 of
`2026-03-invoice-lifecycle-and-communication.md`). Restated for completeness:

| Actor | Capability |
|---|---|
| `admin` | Download any contract PDF; read/update/reset the contract template via the admin template editor |
| `zev_owner` | Download any contract PDF of their own ZEV |
| `participant` | Download only their own contract PDF |
| `guest` | None |

Download endpoint: `GET /api/v1/zev/participants/{pk}/contract-pdf/` — DRF action
`ParticipantViewSet.contract_pdf` (`zev/views.py`), `IsAuthenticated` plus a
manual check: `is_admin` or `is_zev_owner` may fetch any participant;
otherwise `participant.user == request.user` is required (403 otherwise).
Response is a streamed `application/pdf` attachment named
`contract_{last_name}_{first_name}.pdf`.

Template admin endpoints: `GET|PATCH|DELETE
/api/v1/invoices/invoices/contract-pdf-template/` — `PdfTemplateView`
(`invoices/views_templates.py`, `_AdminTemplateView` base, admin only,
audit-logged under `template.contract_pdf.*`).

## 4. Data model

The contract render context is the contract surface, so it is documented here
at field level. The only data-model change in this branch is
`PdfTemplate.default_digest` (migration `invoices/0009`), documented in §5.2
and in `2026-03-admin-governance-and-settings.md` §5.4.

### 4.1 Contract render context

Built by `_build_contract_context(participant)` in `invoices/contract_pdf.py`.

| Key | Type | Derivation |
|---|---|---|
| `participant` | `Participant` | The participant the contract is generated for |
| `owner_participant` | `Participant \| None` | `zev.participants.filter(user=zev.owner).first()` |
| `zev` | `Zev` | `participant.zev` |
| `consumption_mps` | `list[MeteringPoint]` | Metering points of non-ended assignments (valid_to null or `>= today`) with meter type `CONSUMPTION` or `BIDIRECTIONAL` (`MeteringPoint.objects.filter(id__in=assigned_mp_ids)`, DB order) |
| `production_mps` | `list[MeteringPoint]` | Same assignment filter, meter type `PRODUCTION` or `BIDIRECTIONAL` |
| `local_tariff_rows` | `list[dict]` | Active local-energy tariff display rows, see §4.2 |
| `tariff_rule` | `str \| None` | Clause-5 rule paragraph, pre-rendered from `clause_tariff_rule_pct` (with the configured percentage formatted in) or `clause_tariff_rule_flat`, following the first active local tariff's mode; `None` when no local tariff exists |
| `tariff_pct_line` | `str \| None` | Green-box rule line, `tr["tariff_pct_of"]` formatted with the first row's percentage; `None` for flat tariffs |
| `tariff_reference_product` | `str \| None` | `Tariff.notes` of the first row when set — printed under the clause-5 rule as the reference product |
| `billing_interval_display` | `str` | `tr["billing_intervals"].get(zev.billing_interval, zev.billing_interval)` |
| `contract_date` | `str` | `format_date_value(timezone.localdate(), date_pattern)` — the contract is generated on demand, so "today" doubles as the issue date |
| `participation_start` | `str` | `format_date_value(earliest assignment.valid_from or participant.valid_from, date_pattern)` |
| `document_id` | `str` | `"CTR-" + str(participant.pk).replace("-", "")[:8].upper()` — the `Participant.id` UUID is dash-stripped and truncated to 8 chars (12 total), a traceability aid rather than a digest or legal reference |
| `vat_rate_display` | `str` | `""` unless `zev.vat_number`; then `f"{float(rate) * 100:.2f} %"` of `VatRate.active_for_day(timezone.localdate())`, or `""` if no active rate |
| `tr` | `dict` | Copy of `CONTRACT_TRANSLATIONS[zev.invoice_language or "de"]` with `payment_terms_unit` resolved to the singular/plural form based on `zev.payment_term_days == 1`. Copied (not the shared constant) so per-ZEV resolution never leaks into other contracts |
| `lang` | `str` | `zev.invoice_language or "de"` |
| `local_tariff_notes` | `str` | `zev.local_tariff_notes or ""` |
| `additional_contract_notes` | `str` | `zev.additional_contract_notes or ""` |

`date_pattern` is `AppSettings.load().date_format_short`, the same setting the
invoice PDF uses, so both documents print identical date formats.

### 4.2 Local tariff display rows

`_build_local_tariff_display(zev, tr, date_pattern)` returns one dict per
active local tariff (`billing_mode` `ENERGY` or `PERCENTAGE_OF_ENERGY`,
`energy_type` `LOCAL`, `valid_from <= today <= valid_to`):

| Key | Type | Meaning |
|---|---|---|
| `name` | `str` | Tariff name |
| `rate_rp` | `str` | Effective price in Rp/kWh (`f"{rp:.2f}"`), or `f"{pct:.2f}%"` when no grid base price exists |
| `rate_description` | `str` | `tariff_flat`, `tariff_ht`, `tariff_nt`, or a percentage formula like `80.00% × 22.50 Rp./kWh (% des Netzpreises)` |
| `pct` | `str \| None` | Rendered percentage (`f"{pct:.2f}"`) for percentage tariffs, else `None` — drives the green-box rule line and the clause-5 rule |
| `unit` | `str` | `tr["tariff_rp_unit"]`; empty when a percentage tariff has no active grid base price, so the green box renders the bare percentage without a unit |
| `valid_from` / `valid_to` | `str \| None` | Validity dates formatted with `date_pattern`; `valid_to` is `None` when the tariff is open-ended |
| `validity` | `str` | `"01.01.2026 – 31.12.2026"`, or `tr["tariff_valid_open"]` (`"ab {date}"`) for open-ended tariffs |
| `notes` | `str` | `Tariff.notes` (blank when unset) — forwarded so a configured reference product renders in clause 5 |

For percentage tariffs the base is the sum of the flat (or HT) prices of all
active GRID `ENERGY` tariffs of the ZEV; HT and NT rows of a flat-absent tariff
are emitted as separate rows.

## 5. Shared PDF design base

**File:** `backend/templates/pdf/shared_pdf_base.html`

A Django template partial containing one `<style>` block with the common print
design system, extracted verbatim from the invoice template:

- **Design tokens** — `:root` variables: `--ink`, `--ink-soft`, `--muted`,
  `--line`, `--line-subtle`, `--surface`, `--brand`, `--brand-deep`,
  `--brand-mid`, `--brand-pale`, `--brand-glow`, `--gold`, `--brand-accent`,
  `--brand-light`, `--brand-muted`, `--zebra`, `--chart-surface`,
  `--subtotal-color`.
- **Base** — `*` reset, `body` font stack (`Helvetica Neue`, 9.5 pt, `--ink`).
- **Utilities** — `.eyebrow`, `.visually-hidden`.
- **Document header anatomy** — `.document-header` (flex, bottom border,
  brand accent underline via `::after`), `.brand-row`, `.brand-mark`,
  `.company-name`, `.company-address`, `.document-label`, `.document-number`,
  `.document-status`.
- **Page furniture classes** — `.page-meta`, `.page-meta-inner`,
  `.page-meta--header`, `.page-meta--footer`, `.meta-left` (with brand bullet
  via `::before`), `.meta-center`, `.meta-right`.

Consumption contract:

- On-disk default templates include it from `<head>` with
  `{% include "pdf/shared_pdf_base.html" %}`, then define their own `<style>`
  block for document-specific rules (layout, tables, signatures, their own
  `@page` setup).
- The centre page counter text is document-specific (invoice: `N / M`;
  contract: `Seite N von M`), so each document defines its own
  `.page-meta .meta-center::after` content — the partial does not define it.
- The partial is intentionally **not** inlined into customized `PdfTemplate`
  DB overrides (those store one full standalone HTML document), so existing
  overrides keep working untouched when the shared design changes; only a
  reset to default adopts it.

### 5.1 Template comment gotcha (Django 6)

Django 6's template lexer token regex is
`({%.*?%}|{{.*?}}|{#.*?#})` **without `re.DOTALL`**, so a `{# ... #}`
comment **cannot span multiple lines** — a multi-line `{#` is emitted as
literal text into the rendered HTML. If that text contains a literal `<style>`
token it corrupts WeasyPrint's HTML parsing (the real stylesheet gets
swallowed; page layout breaks; see the invoice 2-page regression this spec
fixed). Rule for all templates:

- Use `{% comment %} ... {% endcomment %}` for multi-line comments.
- A `{# ... #}` comment must be a single line.

### 5.2 Template override validation and provenance

PDF-template overrides (`PdfTemplate` rows: invoice, contract, annual
statement) are edited by admins through `PdfTemplateView` in `views_templates.py`.
Two protections ship with this branch:

- **Save-time validation.** `PATCH` renders the submitted content against the
  template's sample context through the `strict-validation` template engine
  (whose `string_if_invalid` emits a sentinel for unknown variables) before
  storing. Syntax errors and **unknown output variables** — including attribute
  typos like `{{ participant.emali }}`, which the default engine silently
  renders as an empty string — are rejected with `400` and nothing is stored.
  Known limitations (documented in the code): variables consulted only inside
  control-flow tags (`{% if %}`/`{% for %}`) never reach a rendering position,
  so a typo there is not detected, and validation exercises Django HTML
  rendering only — WeasyPrint/CSS/PDF-render failures are caught at preview or
  document-render time, not at save time.
- **Staleness tracking.** Each stored override keeps `default_digest`, the
  sha256 of the on-disk default at save time (migration `invoices/0009`).
  `GET` computes `is_stale` by comparing it against the current on-disk
  default, never against a stored flag. Legacy rows backfilled by the
  migration carry the digest of the default shipping in this release and are
  treated as current; a blank digest (template file unresolvable at migrate
  time) means *unknown provenance* and is never stale.

The admin UI (`AdminPdfTemplatesPage.tsx`) shows a stale banner when
`is_customized && is_stale`, and `DELETE` reverts to the on-disk default.

## 6. Contract template anatomy

**File:** `backend/templates/contracts/participant_contract_pdf.html`
`CONTRACT_TEMPLATE_NAME = "contracts/participant_contract_pdf.html"`

Clause headings use `.section-heading`: a `position: relative` block whose
`::after` draws a 1pt `--brand-pale` rule at 50% height across the full
content width; the heading text is wrapped in a `<span>` with
`background: #fff`, `padding-right: 4mm` and `z-index: 1` so it masks the
rule behind the text. This masking pattern (instead of a flex text+rule row)
is deliberate: WeasyPrint's flexbox support shrinks the text item and
mis-aligns the rule when a translation wraps to two lines.

The binding part is a numbered framework agreement (clauses 1–12, numbers
hardcoded in the template as `.clause-num` inside the masked heading span so
all locales share the same numbering), followed by the signature block and a
non-binding appendix. Content flows naturally across pages (`break-inside:
avoid` on cards/blocks); only the appendix forces a break
(`.appendix-part { break-before: page; }`).

1. **Page 1** — full document header in flow: brand row + ZEV name + owner
   address (from `owner_participant`; VAT number line when set) on the left;
   document label (`tr.contract_title`), `document-number` (`document_id`)
   and `document-status` (`tr.contract_date_label` + `contract_date`) on
   the right. Below it an invoice-style `.contract-summary` band: a
   `.facts-grid` surface card with the four key terms as a 2×2 grid
   (participation start, billing interval, payment terms incl. unit, VAT
   with `vat_rate_display` when liable) and a dark `.tariff-card` (gradient
   like the invoice amount card) showing the first local tariff rate with
   `tr.tariff_rp_unit`. The hint line is tariff-type aware: percentage
   tariffs print the rule line `tariff_pct_line` (e.g. "= 80.00 % des
   Standardtarifs des Netzbetreibers"), flat tariffs the tariff name.
   Without local tariffs the card shows `—`
   (`tariff_none`). The band deliberately carries no participant identity — that
   lives only in the clause-1 party cards, so nothing is printed twice.
   Then:
   - `1. Vertragsparteien` (`tr.parties_title`): two `.party-card`s in
     `.parties-grid` (participant / owner). Cards carry the defined-term
     role text (`participant_label`/`owner_label`), `.party-name` and
     `.party-fact` label/value rows; metering points render as monospace
     `.meter-chip`s (dashed `.meter-chip--empty` `CH` chips when none) with
     `field-hint` location descriptions and `tr.meter_hint`. All
     system-known values are pre-filled.
   - `2. Zweck und Geltungsbereich` (`tr.subject_title`): purpose/scope
     prose citing Art. 16–18 EnG, Art. 14–18 EnV, Art. 17a–17c EnG, the
     internal/external split, and the bilateral topology: the agreement is
     concluded between the Manager and each participant, and the identical
     agreements of all participants together form the vZEV's internal
     framework.
   - `3. Begriffe` (`tr.definitions_title`): `.clause-list` of seven
     definitions (`tr.definitions_items`).
2. **Clauses 4–7** — `4.` organisation/mandate of the vZEV Manager
   (`manager_title`, `manager_text` + `manager_duties` list); the mandate
   text separates operational discretion from material decisions, which
   require the consent of all participants (admissions, amendments), and
   adds the annual information duty (tariffs, production, allocation);
   `5.` tariffs and billing (`agreements_title`): tariff table
   (`tariff-table`, brand-deep header row with the numeric column
   right-aligned via `th.num`, zebra rows, right-aligned `td.rate`,
   `tariff-empty` fallback) with a fourth validity column (`row.validity`),
   tariff-note `freetext-box`, then a conditional tariff rule paragraph
   (`tariff_rule`, autoescaped like all output — translation values carry
   no markup, so nothing is rendered `|safe`): percentage-of-grid prints
   `clause_tariff_rule_pct` with the configured percentage formatted in,
   flat tariffs print `clause_tariff_rule_flat` — both describe automatic
   adjustment when the grid operator's prices change and the communication
   duty (with each invoice or at least annually); an optional reference
   product line (`reference_product_label` + `tariff_reference_product` from
   `Tariff.notes`); then the tariff cap (never above the external standard
   tariff; 80% benchmark for tenancies; for tenants the lease and mandatory
   tenancy law prevail), the notification/termination clause (one month
   notice, withdrawal right) and the billing clause (external bill
   redistribution, 5% default interest, suspension on repeated non-payment);
   `6.` metering and allocation
   (`metering_title`/`_text`), mirroring `allocation/split.py`: allocation
   per metering interval (local energy = production consumed in the
   interval, distributed pro rata to simultaneous consumption), exported
   surplus allocated pro rata to the production plants whose owners receive
   the feed-in remuneration; `7.` liability and recourse (solidary liability
   Art. 17 EnG, internal recourse, no minimum-energy entitlement, force
   majeure, and the explicit universal-service guarantee)
   (`liability_title`/`_text`).
3. **Clauses 8–12 + signatures** — `8.` entry/exit/mutations
   (`membership_title`/`_text`; join condition is the vZEV-correct one:
   same grid-operator service area plus the technical vZEV prerequisites,
   each party retaining its own grid connection — not the ZEV
   same-connection topology); `9.` data protection (controller, purposes,
   10-year retention, FADP rights) (`privacy_title`/`_text`); `10.`
   communication and dispute resolution (email deemed received after 3
   days, amicable settlement first) (`communication_title`/`_text`); `11.`
   duration and termination (`tr.duration_title`/`_text`); `12.` final
   provisions (Swiss law, jurisdiction, written form, severability)
   (`tr.jurisdiction_title`/`_text`, incl. a dissolution right with
   appropriate notice when legal or grid-operator requirements no longer
   allow the vZEV to continue); additional agreements freetext box
   (`tr.additional_label`). Then `Unterschriften` (`tr.signatures_title`,
   unnumbered): `.sig-grid` with `break-inside: avoid` (signature block
   never splits across pages); each `.sig-block` pre-fills `.sig-name` with
   the party's full name; only `Ort, Datum` and `Unterschrift` lines stay
   blank for wet signing. Each blank is a `.sig-line` (8mm tall signing
   space, 0.5pt `--ink-soft` bottom border) with its `.sig-line-label`
   caption *below* the line.
4. **Appendix A** (`.appendix-part`, new page) — `h1.appendix-heading`
   `Anhang A` (`tr.appendix_title`) + intro; seven `.info-block`s
   (`break-inside: avoid`): ZEV explainer, vZEV explainer, legal basis list,
   rights/obligations list, joint liability, privacy, tariff provisions.
   The non-binding character is stated exactly once: the heading
   parenthetical and `precedence_note` (which also says the appendix is no
   legal advice and that Appendix B is binding).
5. **Appendix B** (`.appendix-part`, new page after Appendix A) — a
   **binding** part of the contract (`tr.appendix_b_title` +
   `appendix_b_subtitle`, "Bestandteil des Vertrags"): controller identity
   (`privacy_controller_title`/`_text`), purposes, recipient categories
   (`privacy_recipients_*`), a retention table zipped from
   `privacy_retention_categories`/`privacy_retention_periods` (headers
   `privacy_retention_col_data`/`privacy_retention_col_period`) and the
   data-subject rights (FADP, EDÖB complaint route). Clause 9 points to it;
   unlike Appendix A (explicitly non-binding guidance), Appendix B has
   binding contractual effect. The controller address paragraph is written
   on **one source line**: `.clause-text` uses `white-space: pre-line`, so
   any source newline between its `{% if %}`/`{% endif %}` tag pairs would
   render as a line break (this once put the city's leading comma on its own
   line).

### 6.1 Page machinery (footer only)

The contract prints **no running header** — a header plus footer on every
page read as visual noise; the single page-1 document header carries the
identity, and the footer carries the per-page furniture. There is therefore
no named `@page` rule either; one default rule serves every page:

```css
@page {
    size: A4;
    margin: 12mm 0 12mm 0;
    @top-center { content: none; }
    @bottom-center { content: element(footer-meta); width: 210mm; }
}
.page-meta .meta-center::after {
    content: "{{ tr.page_label }} " counter(page) " {{ tr.page_of }} " counter(pages);
}
```

One running element (direct child of `<body>`, same pattern as the invoice):

- `position: running(footer-meta)` — `page-meta page-meta--footer` with
  `{{ zev.name }} · {{ document_id }}` left, `Seite N von M` counter
  center, issue date right.

### 6.2 Removed in the redesign

- The always-empty `Gebäude / Wohnung` field row and its
  `tr.field_building` translation keys (all four locales) — dead space.
- The legacy per-page manually repeated header divs and hardcoded colors;
  all styling now uses tokens from the shared partial.
- The running header on pages 2+ (and the named `contract` `@page` rule it
  required): footer-only page furniture instead.
- The closing `.info-note` disclaimer callout of Appendix A
  (`tr.info_note_title`/`tr.info_note_text`, all four locales) plus its CSS:
  the heading parenthetical and `precedence_note` already state that the
  appendix is non-binding and the agreement prevails, so the callout was a
  third copy of the same sentence. `precedence_note` absorbed its only
  unique statement ("does not constitute legal advice").
- The `tariff_details_5` hint line ("Details: Ziff. 5") on the dark
  `.tariff-card`: the card already shows the first local tariff rate and
  clause 5's table follows on the same spread.

## 7. Translation content

`CONTRACT_TRANSLATIONS` in `invoices/contract_translations.py`: a pure data
module mirroring `invoices/pdf_translations.py`; four locale dicts (`de`,
`fr`, `it`, `en`), **111 keys each**, identical key sets, structure and
placeholder sets (guarded by the translation-parity tests). Translation
values contain **no HTML markup** (asserted by the no-HTML test) so the
template renders them without `|safe`. Keys added by the redesign:
`contract_date_label`, `participation_start_label`, `appendix_title`, and
the `page_label`/`page_of` pairs (previously unused, now consumed by the
page counter). Keys added by the framework-agreement upgrade: clause keys
`definitions_title`/`definitions_items` (7 items), `manager_title`/
`manager_text`/`manager_duties` (5 items), `clause_tariff_cap`,
`clause_tariff_adjustment`, `clause_billing`, `metering_title`/
`metering_text`, `liability_title`/`liability_text`, `membership_title`/
`membership_text`, `privacy_title`/`privacy_text`, `communication_text`
(no `communication_title` — the clause heading is generated in the
template). The tariff labels were rewritten per locale
(`local_tariff_label`, e.g. "Ihr Tarif für lokalen Solarstrom" in de,
"Votre tarif d'énergie solaire locale" in fr). Later in-place text
upgrades (no key changes):
bilateral-framework sentence in `subject_text`, consent governance and
annual information in `manager_text`, tenancy-law reservation in
`clause_tariff_cap`, per-interval allocation plus feed-in remuneration in
`metering_text`, universal-service guarantee in `liability_text`,
grid-operator-area join condition in `membership_text`, and the
regulatory-change dissolution rule in `jurisdiction_text`. Rewritten in
place: `subject_title`/`subject_text`
(now purpose & scope with the EnG/EnV/Mantelerlass references) and
`jurisdiction_title`/`jurisdiction_text` (now final provisions incl.
written form and severability). The percentage-tariff model added
`clause_tariff_rule_pct` (`{pct}` placeholder) and `clause_tariff_rule_flat`
(conditional rule paragraphs for clause 5), `tariff_pct_of` (green-box rule
line), `tariff_valid_label`/`tariff_valid_open` (validity column incl.
open-ended spans) and `reference_product_label`.
`local_tariff_label` now reads "Ihr Tarif für lokalen Solarstrom" etc.
instead of the neutral "(v)ZEV" phrasing; `clause_tariff_adjustment` was
rewritten from an annual review into a notification/termination clause
(automatic adjustment makes the annual review redundant); `info_tariff_text`
now points to the clause-5 rule; `tariff_rp_unit`/`tariff_col_price` use
"Rp./kWh" in de/en. Appendix B keys (all four locales):
`appendix_b_title`, `appendix_b_subtitle` and the structured
privacy-notice set — `privacy_controller_title`/`_text`,
`privacy_purposes_*`, `privacy_recipients_title`/`_text`,
`privacy_retention_title`/`_categories`/`_periods`/
`_col_data`/`_col_period`, plus the data-subject rights / EDÖB complaint
text.

## 8. Shared date formatting

**File:** `backend/invoices/dates.py`

`format_date_value(value: date | datetime | None, pattern: str) -> str` —
extracted verbatim from `invoices/pdf.py`, where it previously lived as the
private `_format_date_value`. Semantics: `None` → `""`; aware datetimes are
localized via `timezone.localtime` before taking `.date()`; patterns map to
`dd.mm.yyyy`, `dd/mm/yyyy`, `mm/dd/yyyy`, `yyyy-mm-dd` (`AppSettings`
constants), with `value.isoformat()` as fallback.

`invoices/pdf.py` keeps a module-level alias
`_format_date_value = format_date_value` so existing callers
(`annual_statement.py`, `tasks.py`, `financial_summary.py`, `pdf.py` itself)
are unchanged.

## 9. Sample preview context

`build_sample_contract_context()` in `invoices/template_context.py` (used by
the admin template-editor preview and the `PdfTemplateView` render endpoint)
gained the new context keys so previews render the new template sections:

`participation_start` (`"01.01.2026"`), `document_id` (`"CTR-3B7A9C21"`),
`vat_rate_display` (`"8.10 %"`), and `zev.payment_term_days` (`30`) so the
payment-terms agreement row renders a value in previews. The sample's single
`local_tariff_rows` entry is a percentage tariff (80%, rate 18.00 Rp./kWh
from a 22.50 Rp./kWh grid base, validity 01.01.–31.12.2026, notes "EKZ
Standardprodukt der Grundversorgung") plus the derived `tariff_pct_line`,
`tariff_rule` and `tariff_reference_product` keys so the preview shows the
formula green-box line and the clause-5 rule; the flat-rate branch is covered
by unit tests. The existing sample keys already include
`contract_date`, `tr`, `lang`, `owner_participant`, `consumption_mps`,
`production_mps`, `local_tariff_rows`, `local_tariff_notes`,
`additional_contract_notes`.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Deployments with a customized contract template keep the legacy design until reset | Low | Documented here and in the admin UI: the redesign ships with the on-disk default; `DELETE` on the template endpoint adopts it |
| Template refactors silently change rendered PDFs (regression found: multi-line `{#` comment corrupted the invoice head, adding a page) | Medium | Render smoke tests assert real PDF page counts for invoice (2/3-page layout) and contract (≥ 3 pages) in all four languages |
| WeasyPrint tolerance of layout edge cases (signature block split, running elements, limited flexbox) | Medium | `.sig-grid` and `.info-block` use `break-inside: avoid`; heading rules use absolute positioning + span masking instead of flex; manual eyeball of de/fr/it/en sample renders before release |
| Clause wording was drafted alongside the redesign, not yet legally reviewed | Medium | Treat `contract_translations.py` as a reviewable draft: a human EnG/EnV/FADP pass is a merge gate before production issuance; the pure-data module keeps the prose reviewable without touching render code |
| `document_id` readability if pks grow | Low | Truncated to 8 chars; collision risk negligible within one ZEV; id is traceability aid, not a legal reference |

## 11. Test plan

### Backend — `invoices/test_contract_context.py`

**`ContractPdfContextTests`** (2 tests):

| Test | Asserts |
|---|---|
| `test_future_metering_point_assignments_are_included_in_contract_context` | Assignments starting in the future still surface their metering points in the context |
| `test_bidirectional_meter_appears_in_consumption_and_production_lists` | A `BIDIRECTIONAL` meter appears in both the consumption and the production inventory |

**`ContractPdfPaymentTermsTests`** (5 tests):

| Test | Asserts |
|---|---|
| `test_payment_terms_unit_follows_the_zevs_configured_term` | Plural form when `payment_term_days != 1` |
| `test_payment_terms_unit_uses_the_default_thirty_days` | Default `30` days → plural |
| `test_payment_terms_unit_is_grammatically_singular_for_one_day` | `payment_term_days == 1` → singular form |
| `test_payment_terms_unit_is_translated_per_zev_invoice_language` | Translation matches the ZEV's language |
| `test_building_one_contracts_context_does_not_leak_into_another` | `tr` is copied per contract; one ZEV's payment terms never leak into another's |

**`ContractPdfContextFieldsTests`** (8 tests):

| Test | Asserts |
|---|---|
| `test_contract_date_follows_app_settings_date_format` | `contract_date` uses `AppSettings.date_format_short` (e.g. `2026-04-15`) |
| `test_contract_date_defaults_to_dd_mm_yyyy` | Default pattern renders `15.04.2026` |
| `test_participation_start_uses_earliest_assignment` | Earliest `MeteringPointAssignment.valid_from` wins |
| `test_participation_start_falls_back_to_participant_valid_from` | No assignments → `participant.valid_from` |
| `test_vat_rate_display_shows_active_rate_when_liable` | `VatRate.active_for_day` shown as `8.10 %` when `vat_number` set |
| `test_vat_rate_display_empty_when_not_liable` | No `vat_number` → `""` |
| `test_vat_rate_display_empty_when_liable_without_active_rate` | `vat_number` without an active rate → `""` |
| `test_document_id_is_short_and_stable` | `CTR-` prefix, 12 chars total |

**`ContractPdfTariffRuleTests`** (6 tests):

| Test | Asserts |
|---|---|
| `test_percentage_tariff_row_carries_pct_price_validity_and_notes` | Percentage row carries `pct` `"80.00"`, effective `rate_rp` `"18.00"` (80% of the 22.50 Rp/kWh grid base), `validity` `"01.01.2026 – 31.12.2026"` and the tariff `notes` |
| `test_percentage_tariff_prints_formula_rule_reference_and_green_box_line` | `tariff_rule` contains the rendered percentage and the reference product; markup shows the rule paragraph, `tariff_pct_line`, the reference-product line and the validity column |
| `test_flat_tariff_falls_back_to_fixed_rate_clause_without_pct_line` | Flat tariff → `tariff_rule` is `clause_tariff_rule_flat`, no `pct`, no `tariff_pct_line`, no reference-product line in markup |
| `test_percentage_tariff_without_grid_base_shows_bare_percentage_without_unit` | No active grid tariff → `rate_rp` `"80.00%"` with empty `unit`; markup renders the bare percentage in the green box |
| `test_open_ended_percentage_tariff_renders_open_validity` | Open-ended tariff (`valid_to` null) → `validity` `"ab 01.01.2026"` via `tariff_valid_open` |
| `test_no_local_tariff_prints_no_rule_and_placeholder_amount` | No local tariffs → no `tariff_rule`, green box renders the `—` placeholder and `tariff-empty` |
| `test_empty_notes_render_blank_box_not_placeholder_prose` | Empty `local_tariff_notes`/`additional_contract_notes` render a blank box, never the German placeholder example text |

**`ContractPdfTranslationParityTests`** (3 tests):

| Test | Asserts |
|---|---|
| `test_all_locales_have_identical_keys_and_structure` | All four locales have identical key sets, dict/list/str structure, and list lengths |
| `test_translation_values_carry_no_html_markup` | No translation value contains HTML markup (prose stays plain text; markup lives in the template, never `\|safe`) |
| `test_all_locales_use_identical_placeholder_sets` | The `{placeholder}` set of every key matches across all four locales (a typo like `{pct}` vs `{pctt}` in one language fails here) |

**`ContractPdfRenderingTests`** (12 tests) — end-to-end smoke tests rendering
real PDFs (WeasyPrint) and asserting markup with the `<style>` blocks stripped
(mirrors `invoices/test_pdf.py::_render_invoice_markup`):

| Test | Asserts |
|---|---|
| `test_renders_pdf_in_all_four_languages_with_running_page_machinery` | `generate_contract_pdf` yields a PDF (`%PDF-1.7`) of ≥ 3 pages (pypdf) in de/fr/it/en; markup contains the translated title, `running(footer-meta)`, `page-meta--footer`, `counter(page)`, `counter(pages)`, and asserts `running(header-meta)` is absent (footer-only furniture) |
| `test_page_1_uses_the_invoice_document_header_anatomy` | `document-header`, `document-label`, `document-number`, `document-status`, `Ausstellungsdatum`, `parties-grid` present |
| `test_known_values_are_prefilled_and_vat_rate_is_rendered` | Participant/owner names, assigned meter ids, `8.10 %`, VAT number, and participation start all render |
| `test_sample_contract_context_renders` | `build_sample_contract_context()` renders without error and contains the sample `document_id` |
| `test_appendix_b_renders_the_structured_privacy_notice` | Appendix B shows controller identity (owner name), purposes, retention table and data-subject rights; the controller address renders on one line (`Solarweg 1, 8000 Zürich`) — pre-line would turn any source newline into a line break |
| `test_summary_sheet_is_not_part_of_the_signed_document` | The plain-language summary is not part of the signed contract; Appendix A opens with the non-binding/precedence-note heading; no `info-note` box (the removed disclaimer) |
| `test_corrected_contract_clauses_render_without_unsafe_shortcuts` | The signed document renders the legal/operational guardrails without promising unrestricted clauses |
| `test_no_page_is_left_nearly_empty` | Every PDF page carries ≥ 100 extracted characters (guards against a near-empty page) |
| `test_signature_block_is_never_split_across_pages` | The page with `Unterschriften` also contains `Ort, Datum` and `Unterschrift` (`.sig-section` travels as one block) |
| `test_free_text_notes_keep_line_breaks_and_escape_markup` | Multiline notes keep line breaks; markup in notes is HTML-escaped; `.freetext-box` uses `white-space: pre-line` |
| `test_very_long_notes_do_not_balloon_the_document` | A ~3,800-char note keeps the PDF within bounds and Appendix B still renders last |
| `test_unassigned_meter_placeholder_is_neutral` | Without assignments the markup shows the translated "no metering point" statement and never a bare chip |

Total: 37 test methods across 6 classes in `test_contract_context.py`.

### Backend — `invoices/test_template_admin.py`

**`TemplateAdminPermissionTests`** (6), **`EmailTemplateAdminTests`** (4),
**`PdfTemplatePreviewTests`** (4), **`PdfTemplateAdminTests`** (3) and
**`PdfTemplateOverrideIntegrityTests`** (8) — 25 test methods across 5
classes. The override-integrity class guards save-time validation
(`test_broken_override_is_rejected_and_nothing_is_stored`,
`test_patch_rejects_unknown_template_variables`), staleness
(`test_valid_override_is_stored_with_default_digest_and_not_stale`,
`test_get_flags_override_saved_against_an_older_default_as_stale`,
`test_override_without_digest_provenance_is_never_stale`,
`test_default_template_is_never_stale`) and the legacy-override compatibility
claims (`test_override_with_shared_base_include_renders_through_the_real_path`,
`test_legacy_override_without_include_still_renders`).

### Regression coverage in `invoices/test_pdf.py`

The invoice refactor (CSS extraction into the shared partial) is guarded by
the existing `InvoicePdfRenderingTests`, notably the exact page-count tests
(`test_short_invoice_renders_two_pages`, `test_long_invoice_forces_three_pages`,
inline-QR geometry tests) — these caught the multi-line `{#` comment bug
described in §5.1.

### Validation commands

- `python -m pytest -q` — full backend suite green (see §11 for the counts
  verified against this branch).
- `ruff check invoices/` — lint clean.
- `python manage.py makemigrations --check --dry-run` — no missing migrations.
- Manual: render de/fr/it/en sample PDFs via the admin template preview
  (`/api/v1/invoices/invoices/contract-pdf-template/` POST) and eyeball
  pagination — signature block must not split, footer on every page.

### Acceptance criteria

- [ ] Invoice and contract PDFs include the same shared design base; invoice
      markup unchanged (only CSS extracted).
- [ ] Contract renders: page 1 document header, running footer on every page (no running header),
      `Seite N von M` counters on every page.
- [ ] All system-known values pre-filled (owner address, participation start,
      active VAT rate, document id); only signature/date lines blank.
- [ ] No `Gebäude / Wohnung` field anywhere in the contract template or
      translation dicts.
- [ ] Full backend suite green; ruff clean.
- [ ] This spec's field names, paths, and test counts verified against code.
