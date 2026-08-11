# Baseline Spec: Contract PDF Redesign

- Spec ID: SPEC-2026-08-contract-pdf-redesign
- Status: Approved
- Scope: Medium
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
| Tests | `invoices/test_contract_context.py`: context fields, translation + placeholder parity, tariff rule, blank-box placeholders, four-language end-to-end renders and contract issuance; `invoices/test_template_admin.py`: override-integrity tests (save-time validation, staleness), include-through-override compatibility |
| Template admin | `PdfTemplate` overrides are validated before they are stored (PATCH rejects syntax errors and unknown output variables with `400`), and customizations are stale-tracked via `PdfTemplate.default_digest` + `is_stale` (migration `invoices/0009`, admin UI stale banner) — see §5.2 |
| Docs | This baseline spec |
| Legal wording | Clause texts were updated alongside the layout (see §7): clauses 2 (purpose/scope with EnG/EnV citations), 4 (mandate + annual information duty), 5 (binding tariff rule, cap with tenancy-law reservation, notification/termination, billing), 6 (per-interval allocation, feed-in remuneration), 7 (universal-service guarantee), 8 (grid-operator-area join condition), 10 (communication) and 12 (regulatory-change dissolution). `Anhang B` adds a **binding** privacy notice (controller, purposes, recipients, retention table, data-subject rights) |

### Out of scope

- No new endpoints, permissions or serializers; the download endpoint keeps
  its path and permission model, but its behavior now issues or reuses a
  persisted versioned snapshot — see §13.
- No frontend changes beyond the template-validation work: the admin template
  editor (`AdminPdfTemplatesPage.tsx`) gains an override-staleness banner,
  accessible tab roles (roving tabindex + arrow-key navigation) and the
  redesigned contract template's fields in the editor reference.
- Three data-model additions: `PdfTemplate.default_digest` (migration
  `invoices/0009`) for stale-override detection, plus the `ContractIssue`
  snapshot table and per-ZEV `contract_counter` (migrations `invoices/0010`,
  `zev/0017`) behind the versioned download — see §13. `PATCH` now validates
  overrides before storing (see §5.2).
- The contract download flow records `contract.issue`, `contract.download`
  and (on raced minting) `contract.number_gap` audit events. Template-admin
  mutations keep their audit trail; non-admin attempts are DENIED-logged by
  the shared `_AdminTemplateView` base (`views_templates.py`).
- Customized `PdfTemplate` DB overrides for the contract keep rendering their
  stored standalone HTML and are **not** migrated — the redesign only reaches
  them after a reset to default (DELETE on the template endpoint).
- The plain-language summary page is reworded into the non-binding
  `Anhang A`; the legally binding clause-wording changes listed in §1/§7
  were updated alongside the layout and are in scope above.

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
`contract_{last_name}_{first_name}_v{version}.pdf` (versioned snapshot, see
§13).

Template admin endpoints: `GET|PATCH|DELETE
/api/v1/invoices/invoices/contract-pdf-template/` — `PdfTemplateView`
(`invoices/views_templates.py`, `_AdminTemplateView` base, admin only,
audit-logged under `template.contract_pdf.*`).

## 4. Data model

The contract render context is the contract surface, so it is documented here
at field level. The redesign itself needs no schema changes; the branch adds
`PdfTemplate.default_digest` (migration `invoices/0009`, see §5.2 and
`2026-03-admin-governance-and-settings.md` §5.4), and the versioned download
adds a `ContractIssue` snapshot table and a per-ZEV `contract_counter`
column (migrations `invoices/0010`, `zev/0017`) — documented in §13.

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
| `document_id` | `str` | Stable per-ZEV document number `CTR-YYYY-NNNN` for issued contracts (see §13); the pure render path falls back to `"CTR-" + str(participant.pk).replace("-", "")[:8].upper()` — a truncated uppercase UUID string (`Participant.id` is a UUID), not a digest or cryptographic identifier |
| `vat_rate_display` | `str` | `""` unless `zev.vat_number`; then `f"{float(rate) * 100:.2f} %"` of `VatRate.active_for_day(as_of)` (`timezone.localdate()`), or `""` if no active rate |
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

Django 6's template lexer cannot match multi-line `{# ... #}` comments:
the token regex `({%.*?%}|{{.*?}}|{#.*?#})` has no `re.DOTALL`, so a
multi-line `{#` is emitted as literal HTML; a literal `<style>` token inside
it corrupts WeasyPrint's parsing (stylesheet swallowed, pagination breaks —
this was the invoice 2-page regression). Rules for all templates:

- Single-line `{# ... #}` comments only.
- Use `{% comment %} ... {% endcomment %}` for multi-line comments.

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

**Files:** `backend/templates/contracts/participant_contract_pdf.html`;
`CONTRACT_TEMPLATE_NAME = "contracts/participant_contract_pdf.html"`.

Clause headings use `.section-heading`: a `position: relative` block whose
`::after` draws a 1pt `--brand-pale` rule at 50% height; the title sits in a
`<span>` (`background: #fff`, `padding-right: 4mm`, `z-index: 1`) that masks
the rule behind the text. The masking (not a flex text+rule row) is
deliberate: WeasyPrint's flexbox shrinks the text item and mis-aligns the
rule on two-line translations. Binding clause numbers 1–11 are hardcoded
`.clause-num` inside the mask so all locales share the same numbering.

Content flows naturally (`break-inside: avoid` on cards/blocks); only
`.sig-section`/`.appendix-part { break-before: page; }` force page breaks.

| Block | Keys | Layout |
|---|---|---|
| Page-1 document header | `contract_title`, `contract_date_label`; `document-number`/`document-status` markup | Brand row + ZEV name + owner address left (VAT number line when set); document label, `document_id`, issue date right |
| Summary band | `participation_start_label`, `billing_interval_label`, `payment_terms_label` (unit resolved at render, §4.1), `vat_label`/`vat_required`/`vat_not_required`, `local_tariff_label`, `tariff_rp_unit`, `tariff_pct_line`, `tariff_none` | `.contract-summary`: `.facts-grid` 2×2 (participation start, billing interval, payment terms, VAT when liable) + dark `.tariff-card` with the first local tariff rate and exactly one tariff-type-aware hint line (percentage: `tariff_pct_line`; flat: tariff name); `—` when no local tariffs. No participant identity (lives only in clause 1), no `Details: Ziff. 5` pointer — clause 5's table carries the full tariff |
| Clause 1 — parties | `parties_title`, `participant_label`, `owner_label`, `field_address`/`field_phone`/`field_email`, `field_meter`/`field_meter_pv`, `meter_hint`, `meter_none` | Two `.party-card`s in `.parties-grid`; `.party-name` + `.party-fact` rows; metering points as monospace `.meter-chip`s (neutral `meter_none` when none); all system-known values pre-filled |
| Clause 2 — purpose/scope | `subject_title`, `subject_text` | Art. 16–18 EnG, Art. 14–18 EnV, Art. 17a–17c EnG; internal/external split; bilateral Manager↔participant agreements together form the vZEV framework |
| Clause 3 — definitions | `definitions_title`, `definitions_items` (7) | `.clause-list` |
| Clause 4 — manager mandate | `manager_title`, `manager_text`, `manager_duties` (5) | Operational discretion vs. material decisions (consent of all participants); annual information duty |
| Clause 5 — tariffs/billing | `agreements_title`, `local_tariff_label`/`local_tariff_unit`/`local_tariff_note`, `tariff_col_name`/`tariff_col_calc`/`tariff_col_price`, `tariff_valid_label`, `clause_tariff_rule_lead`, `clause_tariff_cap_lead`/`clause_tariff_cap`, `clause_tariff_adjustment_lead`/`clause_tariff_adjustment`, `clause_billing_lead`/`clause_billing`, `reference_product_label` | `.tariff-table` (brand-deep header, right-aligned `th.num`, zebra `td.rate`, `tariff-empty` fallback, validity column); `.freetext-box` notes (`white-space: pre-line`, `overflow-wrap: anywhere`); conditional `tariff_rule` paragraph (percentage or flat, see §7), optional reference-product line, cap, notification/termination and billing paragraphs |
| Clause 6 — metering/allocation | `metering_title`, `metering_text` | Per-interval pro-rata allocation (mirrors `allocation/split.py`); exported surplus pro rata to the production plants |
| Clause 7 — liability | `liability_title`, `liability_text` | Solidary liability (Art. 17 EnG), internal recourse, no minimum-energy entitlement, force majeure, universal-service guarantee |
| Clause 8 — entry/exit | `membership_title`, `membership_text` | Statutory common-self-consumption conditions at the place of production; grid operator's assessment/registration process decisive; own grid connection retained |
| Clause 9 — data protection | `privacy_title`, `privacy_text` | Controller, purposes, statutory retention, FADP rights; points to the binding Appendix B below |
| Clause 10 — duration | `duration_title`, `duration_text` | Owners' two-month route subject to the grid-operator mutation process; tenants under mandatory tenancy law; exit effective only once the metering/supply arrangement is implemented |
| Clause 11 — final provisions | `jurisdiction_title`, `jurisdiction_text`, `communication_text` | Email deemed received after 3 days, amicable settlement first, Swiss law, jurisdiction, written form, severability, dissolution right on regulatory change |
| Additional agreements | `additional_label` | Freetext box |
| Signatures | `signatures_title`, `sig_intro`, `sig_owner`, `sig_participant`, `sig_place_date`, `sig_signature` | One `.sig-section` (`break-inside: avoid`): heading + intro + `.sig-grid`; each `.sig-block` pre-fills `.sig-name`; only `Ort, Datum` and `Unterschrift` stay blank — `.sig-line` blanks (7 mm tall, 0.5 pt `--ink-soft` underline, label below) |
| Appendix A | `appendix_title`, `precedence_note`, `info_subtitle`, `info_zev_title`/`info_zev_text`, `info_vzev_title`/`info_vzev_text`, `info_legal_title`/`info_legal_items`, `info_rights_title`/`info_rights_items`, `info_liability_title`/`info_liability_text`, `info_privacy_title`/`info_privacy_text`, `info_tariff_title`/`info_tariff_text` | New page; `h1.appendix-heading`; seven `.info-block`s (`break-inside: avoid`) — ZEV explainer, vZEV explainer, legal basis, rights/obligations, joint liability, privacy, tariff provisions. The non-binding character is stated exactly once: the heading parenthetical and `precedence_note` (which also says the appendix is no legal advice and that Appendix B is binding) |
| Appendix B | `appendix_b_title`, `appendix_b_subtitle`, `privacy_short`, `privacy_controller_title`/`privacy_controller_text`, `privacy_purposes_title`/`privacy_purposes_items`, `privacy_recipients_title`/`privacy_recipients_text`, `privacy_retention_title`/`privacy_retention_col_data`/`privacy_retention_col_period`, `privacy_rights_title`/`privacy_rights_items` | New page; **binding** privacy notice (`Datenschutzerklärung – Bestandteil des Vertrags`): controller identity, purposes, recipient categories, a retention table zipped from `privacy_retention_categories` × `privacy_retention_periods` (4 rows, §7) and the data-subject rights incl. the EDÖB complaint route. Unlike Appendix A (explicitly non-binding), it has binding contractual effect. The controller address paragraph is written on **one source line**: `.clause-text` uses `white-space: pre-line`, so any source newline between the `{% if %}`/`{% endif %}` tag pairs would render as a line break (this once put the city's leading comma on its own line) |

### 6.1 Page machinery (footer only)

No running header — header + footer on every page reads as noise, and the
page-1 document header already carries the identity. One default `@page`
rule serves every page (no named rule needed):

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
`position: running(footer-meta)` on `page-meta page-meta--footer` —
`{{ zev.name }} · {{ document_id }}` left, the page counter center, the
issue date right.

### 6.2 Removed in the redesign

- The always-empty `Gebäude / Wohnung` field row and its `field_building`
  translation keys (all four locales).
- Legacy per-page manually repeated header divs and hardcoded colors — all
  styling now uses tokens from the shared partial.
- The running header on pages 2+ and the named `contract` `@page` rule it
  required: footer-only page furniture instead.
- The plain-language summary sheet (`summary_title`/`summary_note`/
  `summary_points`) — the signed document no longer carries a second summary
  layer (Appendix A opens with the `precedence_note` hierarchy statement);
  its "Tarifstabilität: Anpassungen höchstens jährlich" bullet also
  contradicted the clause-5 automatic-adjustment rule.
- The fake empty `CH` metering-point chips (leftover after
  `field_meter_second` was dropped) — replaced by one neutral `meter_none`
  statement per meter group.
- Absolute privacy guarantees that were not operationally enforced
  (10-year retention, deletion of aggregated high-resolution data, no
  cross-border transfer) — Appendix B now states statutory retention and a
  conditional cross-border transfer ("nur, soweit gesetzlich zulässig und
  erforderlich").
- The closing `.info-note` disclaimer box of Appendix A
  (`info_note_title`/`info_note_text`, all four locales) plus its CSS: the
  heading parenthetical and `precedence_note` already stated that the
  appendix is non-binding and the agreement prevails, so the box was a third
  copy of the same sentence. `precedence_note` absorbed its only unique
  statement ("does not constitute legal advice").
- The `tariff_details_5` hint line ("Details: Ziff. 5") on the dark
  `.tariff-card`: the card already shows the first local tariff rate and
  clause 5's table follows on the same spread.

## 7. Translation content

`CONTRACT_TRANSLATIONS` in `invoices/contract_translations.py` (pure data
module, mirroring `invoices/pdf_translations.py`): four locales
(`de`, `fr`, `it`, `en`), **111 keys each**, identical key sets and
structure (guarded by `test_all_locales_have_identical_keys_and_structure`).

New keys by change phase:

| Phase | Keys |
|---|---|
| Redesign | `contract_date_label`, `participation_start_label`, `appendix_title`, `page_label`/`page_of` (page counter) |
| Clause 3 | `definitions_title`, `definitions_items` (7) |
| Clause 4 | `manager_title`, `manager_text`, `manager_duties` (5) |
| Clause 5 | `clause_tariff_cap`, `clause_tariff_adjustment`, `clause_billing`, `clause_tariff_rule_pct` (`{pct}` placeholder), `clause_tariff_rule_flat`, `tariff_pct_of`, `tariff_rp_unit`, `tariff_col_price`, `tariff_valid_label`, `tariff_valid_open`, `reference_product_label` |
| Clauses 6–11 | `metering_title`/`metering_text`, `liability_title`/`liability_text`, `membership_title`/`membership_text`, `privacy_title`/`privacy_text`, `communication_text` |
| Appendix B | `privacy_controller_title`/`privacy_controller_text`, `privacy_purposes_title`/`privacy_purposes_items` (3), `privacy_recipients_title`/`privacy_recipients_text`, `privacy_retention_title`/`privacy_retention_col_data`/`privacy_retention_col_period`, `privacy_retention_categories` (4)/`privacy_retention_periods` (4), `privacy_rights_title`/`privacy_rights_items` (5) |
| Review pass | `meter_none`, `precedence_note`, and the `*_lead` template keys (`clause_tariff_rule_lead`, `clause_tariff_cap_lead`, `clause_tariff_adjustment_lead`, `clause_billing_lead`) |

Rules and in-place updates:

- **No HTML in values.** No string or list item contains a tag — the
  template renders `<strong>{{ tr.…_lead }}</strong>` itself, so nothing is
  rendered `|safe` (`test_translation_values_carry_no_html_markup`).
- **Removed dead keys** from all locales: `field_name`, `sig_name`,
  `field_meter_second`, `info_title`, `contract_date`, `summary_title`/
  `summary_note`/`summary_points`, and (with the Appendix-A disclaimer box)
  `info_note_title`/`info_note_text` and the `tariff_details_5` card hint.
- **Placeholder prose** (`local_tariff_note_placeholder`,
  `additional_placeholder`) renders only in admin previews (`is_preview`);
  issued contracts print a blank box.
- **In-place text upgrades** (no key changes): `subject_*` (EnG/EnV/
  Mantelerlass references, bilateral framework), `jurisdiction_*` (final
  provisions incl. written form/severability), per-interval allocation and
  feed-in remuneration in `metering_text`, tenancy-law reservation in
  `clause_tariff_cap`, universal-service guarantee in `liability_text`,
  grid-operator-area join condition in `membership_text`; percentage-tariff
  model reworked `clause_tariff_adjustment` into a notification/termination
  clause; `local_tariff_label` now reads "Ihr Tarif für lokalen Solarstrom"
  etc.; the document-header VAT label uses `vat_label`; the German
  `owner_label` reads "vZEV-Verantwortlicher" (typed variants in the other
  three locales).
- **Derived keys (not in the dict).** At render time the `tr` copy used by the
  template additionally receives `payment_terms_unit` (singular/plural from
  `zev.payment_term_days`, §4.1) and `privacy_retention_rows` (zipped
  `privacy_retention_categories` × `privacy_retention_periods`); the sample
  preview context does the same (see §9).

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
by unit tests. The sample sets `is_preview: True` so the template editor
preview can show placeholder guidance in empty freetext boxes — issued
contracts never do. The existing sample keys already include
`contract_date`, `tr`, `lang`, `owner_participant`, `consumption_mps`,
`production_mps`, `local_tariff_rows`, `local_tariff_notes`,
`additional_contract_notes`.

## 10. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Deployments with a customized contract template keep the legacy design until reset | Low | Documented here and in the admin UI: the redesign ships with the on-disk default; `DELETE` on the template endpoint adopts it |
| Template refactors silently change rendered PDFs (regression found: multi-line `{#` comment corrupted the invoice head, adding a page) | Medium | Render smoke tests assert real PDF page counts for invoice (2/3-page layout) and contract (3–7 pages, no nearly-empty page, signature block never split) in all four languages |
| WeasyPrint tolerance of layout edge cases (signature block split, running elements, limited flexbox) | Medium | `.sig-section` (intro + grid) and `.info-block` use `break-inside: avoid`; heading rules use absolute positioning + span masking instead of flex; manual eyeball of de/fr/it/en sample renders before release |
| Clause wording was drafted alongside the redesign, not yet legally reviewed | Medium | Treat `contract_translations.py` as a reviewable draft: a human EnG/EnV/FADP pass is a merge gate before production issuance; the pure-data module keeps the prose reviewable without touching render code |
| `document_id` traceability and collisions | Low | Issued contracts carry `CTR-YYYY-NNNN`, a per-ZEV sequence minted under the counter row lock (§13) — collisions impossible, number gaps audited; only the pure render path (previews/samples) falls back to an 8-char truncated participant-pk string, a traceability aid, not a legal reference |

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

**`ContractPdfTariffRuleTests`** (7 tests):

| Test | Asserts |
|---|---|
| `test_percentage_tariff_row_carries_pct_price_validity_and_notes` | Percentage row carries `pct` `"80.00"`, effective `rate_rp` `"18.00"` (80% of the 22.50 Rp/kWh grid base), `validity` `"01.01.2026 – 31.12.2026"` and the tariff `notes` |
| `test_percentage_tariff_prints_formula_rule_reference_and_green_box_line` | `tariff_rule` contains the rendered percentage and the reference product; markup shows the rule paragraph, `tariff_pct_line`, the reference-product line and the validity column |
| `test_flat_tariff_falls_back_to_fixed_rate_clause_without_pct_line` | Flat tariff → `tariff_rule` is `clause_tariff_rule_flat`, no `pct`, no `tariff_pct_line`, no reference-product line in markup |
| `test_percentage_tariff_without_grid_base_shows_bare_percentage_without_unit` | No active grid tariff → `rate_rp` `"80.00%"` with empty `unit`; markup renders the bare percentage in the green box |
| `test_open_ended_percentage_tariff_renders_open_validity` | Open-ended tariff (`valid_to` null) → `validity` `"ab 01.01.2026"` via `tariff_valid_open` |
| `test_no_local_tariff_prints_no_rule_and_placeholder_amount` | No local tariffs → no `tariff_rule`, green box renders the `—` placeholder and `tariff-empty` |
| `test_empty_notes_render_blank_box_not_placeholder_prose` | Empty notes print a blank freetext box on real contracts — never the German example prose (`freetext-placeholder` absent) |

**`ContractPdfTranslationParityTests`** (3 tests):

| Test | Asserts |
|---|---|
| `test_all_locales_have_identical_keys_and_structure` | All four locales have identical key sets, dict/list/str structure, and list lengths |
| `test_translation_values_carry_no_html_markup` | No translation string or list item in any locale contains an HTML tag — markup (bold lead-ins) lives in the template, so nothing needs `|safe` |
| `test_all_locales_use_identical_placeholder_sets` | Every `{placeholder}` in a key's value matches across all four locales (catches a typo that would only blow up at render time in one language) |

**`ContractPdfRenderingTests`** (12 tests) — end-to-end smoke tests rendering
real PDFs (WeasyPrint) and asserting markup with the `<style>` blocks stripped
(mirrors `invoices/test_pdf.py::_render_invoice_markup`):

| Test | Asserts |
|---|---|
| `test_renders_pdf_in_all_four_languages_with_running_page_machinery` | `generate_contract_pdf` yields a PDF (`%PDF-1.7`) of 3–7 pages (pypdf) in de/fr/it/en; markup contains the translated title, `running(footer-meta)`, `page-meta--footer`, `counter(page)`, `counter(pages)`, and asserts `running(header-meta)` is absent (footer-only furniture) |
| `test_page_1_uses_the_invoice_document_header_anatomy` | `document-header`, `document-label`, `document-number`, `document-status`, `Ausstellungsdatum`, `parties-grid` present |
| `test_known_values_are_prefilled_and_vat_rate_is_rendered` | Participant/owner names, assigned meter ids, `8.10 %`, VAT number, and participation start all render |
| `test_sample_contract_context_renders` | `build_sample_contract_context()` renders without error and contains the sample `document_id` |
| `test_appendix_b_renders_the_structured_privacy_notice` | Appendix B shows controller identity (owner name), purposes, retention table (incl. `10 Jahre (gesetzliche Aufbewahrungspflicht)`) and rights (incl. `EDÖB`); the controller address renders on one line (`Solarweg 1, 8000 Zürich`) — pre-line would turn any source newline into a line break |
| `test_summary_sheet_is_not_part_of_the_signed_document` | No `summary-sheet` markup, no "Auf einen Blick"/"Günstiger Lokalstrom"/"Tarifstabilität"; Appendix A renders its general/non-binding heading and `precedence_note` hierarchy statement; no `info-note` box (the removed disclaimer) |
| `test_corrected_contract_clauses_render_without_unsafe_shortcuts` | The signed document renders the legal/operational guardrails (tenancy-law reservation, grid-operator-area join condition, universal-service guarantee, regulatory-change dissolution) without promising unrestricted clauses |
| `test_no_page_is_left_nearly_empty` | Every page carries ≥ 100 extracted characters (guards against the previous signatures-only page of ~180 chars) |
| `test_signature_block_is_never_split_across_pages` | The page with `Unterschriften` also contains `Ort, Datum` and `Unterschrift` (heading + intro + grids travel as one `.sig-section`) |
| `test_free_text_notes_keep_line_breaks_and_escape_markup` | Multiline notes keep `

` in the rendered markup, `<script>` content is HTML-escaped, and the `.freetext-box` rule sets `white-space: pre-line` + `overflow-wrap: anywhere` |
| `test_very_long_notes_do_not_balloon_the_document` | A ~3,800-char note keeps the PDF ≤ 12 pages and Appendix B still renders last |
| `test_unassigned_meter_placeholder_is_neutral` | Without assignments the markup shows the `meter_none` statement once per meter group and never a bare `CH` chip |

**`ContractIssuanceTests`** (11 tests):

| Test | Asserts |
|---|---|
| `test_first_download_issues_version_one_with_sequence_number` | First issue → version 1, `CTR-2026-0001`, PDF stored, sha256 `context_hash`, `zev.contract_counter` incremented |
| `test_unchanged_redownload_reuses_the_frozen_snapshot` | Identical rendered HTML → the stored issue is returned, no new row, byte-identical PDF |
| `test_redownload_on_a_later_calendar_day_reuses_the_frozen_snapshot` | The "today" date in the rendered document does not force a new version on a later day |
| `test_concurrent_identical_issuances_mint_a_single_version` | Two threads rendering identical content under the Zev row lock produce one issue; the unused minted number is audited as a `contract.number_gap` event |
| `test_contract_issues_survive_participant_and_zev_deletion` | `ContractIssue` rows are not cascade-deleted with participant or ZEV (snapshot persists) |
| `test_data_change_bumps_version_and_number` | A tariff change mints version 2 with `CTR-2026-0002` and different bytes |
| `test_document_number_sequence_is_per_zev` | Two ZEVs each start at `CTR-2026-0001` |
| `test_new_issue_renders_the_stable_document_number_in_the_pdf` | The rendered document embeds the stable `document_id` |
| `test_contract_pdf_endpoint_streams_the_issued_snapshot` | `GET /api/v1/zev/participants/{pk}/contract-pdf/` streams `application/pdf`, filename carries `_v1`, unchanged re-download adds no issue but writes a `contract.download` audit event |
| `test_concurrent_first_issuances_get_distinct_versions` | A request that read `latest` before a competing first issuance committed derives the version from the row visible under the Zev row lock — no `(participant, version)` collision |
| `test_issue_zev_is_derived_from_the_participant` | `ContractIssue.save()` derives the denormalized `zev` from `participant.zev` |

Total: 48 test methods across 7 classes in `test_contract_context.py`.

### Backend — `invoices/test_template_admin.py`

**`TemplateAdminPermissionTests`** (6), **`EmailTemplateAdminTests`** (4),
**`PdfTemplatePreviewTests`** (4), **`PdfTemplateAdminTests`** (3) and
**`PdfTemplateOverrideIntegrityTests`** (8) — 25 test methods across 5
classes.

**`PdfTemplateOverrideIntegrityTests`** (8 tests):

| Test | Asserts |
|---|---|
| `test_broken_override_is_rejected_and_nothing_is_stored` | PATCH with broken template syntax → 400, no `PdfTemplate` row |
| `test_valid_override_is_stored_with_default_digest_and_not_stale` | PATCH validates via render; row stores `default_digest`, response `is_stale: false` |
| `test_get_flags_override_saved_against_an_older_default_as_stale` | A stored digest that no longer matches the on-disk default → `is_stale: true` on GET |
| `test_override_without_digest_provenance_is_never_stale` | A row with blank `default_digest` (no provenance) → `is_customized: true`, `is_stale: false` |
| `test_patch_rejects_unknown_template_variables` | `{{ participant.emali }}` renders as a sentinel under the strict-validation engine → 400 naming the variable, nothing stored |
| `test_default_template_is_never_stale` | No row → `is_customized: false`, `is_stale: false` |
| `test_override_with_shared_base_include_renders_through_the_real_path` | Current default stored as override still resolves `{% include "pdf/shared_pdf_base.html" %}` through the real `generate_contract_pdf` path (shared-base CSS present) |
| `test_legacy_override_without_include_still_renders` | A pre-redesign override with its own full markup still renders a PDF without error |

(8 methods — the class also guards the compat claim that old overrides keep
working.)

### Regression coverage in `invoices/test_pdf.py`

The invoice refactor (CSS extraction into the shared partial) is guarded by
the existing `InvoicePdfRenderingTests`, notably the exact page-count tests
(`test_short_invoice_renders_two_pages`, `test_long_invoice_forces_three_pages`,
inline-QR geometry tests) — these caught the multi-line `{#` comment bug
described in §5.1.

### Validation commands

- `python -m pytest -q` — full backend suite green, 1103 tests (incl.
  contract context, issuance and template-override tests).
- `ruff check invoices/` — lint clean.
- `python manage.py makemigrations --check --dry-run` — no missing migrations.
- `npm run test:unit` + `npm run build` — frontend (template editor field
  reference and stale banner) green.
- Manual: render de/fr/it/en sample PDFs via the admin template preview
  (`/api/v1/invoices/invoices/contract-pdf-template/` POST) and eyeball
  pagination — signature block must not split, footer on every page.

### Acceptance criteria

- [x] Invoice and contract PDFs include the same shared design base; invoice
      markup unchanged (only CSS extracted).
- [x] Contract renders: page 1 document header, running footer on every page (no running header),
      `Seite N von M` counters on every page.
- [x] All system-known values pre-filled (owner address, participation start,
      active VAT rate, document id); only signature/date lines blank.
- [x] No `Gebäude / Wohnung` field anywhere in the contract template or
      translation dicts.
- [x] Empty freetext notes print a blank box on issued contracts — never
      placeholder prose; placeholders exist only in admin previews.
- [x] PDF-template PATCH validates by rendering before storing; broken
      overrides are rejected with 400 and nothing is persisted.
- [x] Overrides carry `default_digest`; GET/PATCH surface `is_stale` when the
      on-disk default changed since the override was saved (migration `0009`
      backfills legacy rows; blank digest is never stale).
- [x] Contract downloads freeze a versioned snapshot (`ContractIssue`,
      `CTR-YYYY-NNNN` per-ZEV sequence); unchanged re-downloads reuse it and
      data changes mint a new version.
- [x] Concurrent issuances cannot collide on number or version; re-downloads
      are audited (`contract.download`), issuance writes `contract.issue`,
      unused minted numbers write `contract.number_gap`.
- [x] The passing of a calendar day does not re-issue a contract (renders
      reproduce `rendered_on`); concurrent identical issuances mint one
      version.
- [x] Issued snapshots survive participant/ZEV deletion (SET_NULL archive);
      PDF-template PATCH rejects unknown template variables with 400.
- [x] Full backend suite green; ruff clean.
- [x] This spec's field names, paths, and test counts verified against code.

## 12. Template-override hardening

The whole-document override model (a `PdfTemplate` row replacing the on-disk
HTML) is kept, but is now validated at the door and provenance-aware:

- **PATCH validates before storing.** `PdfTemplateView.patch` renders the
  submitted content against its sample context (same helper as the preview
  endpoint, `_render_with_sample_context`) and returns 400 on any render
  error — a broken override or one with a template syntax error can no
  longer be saved to fail later at document-render (email) time. Validation
  additionally runs in **strict mode** through the dedicated
  `strict-validation` template engine (`config/settings.py`, `string_if_invalid`
  sentinel): Django normally renders unknown variables as an empty string, so
  a typo like `{{ participant.emali }}` would silently produce a broken PDF —
  the sentinel turns any unknown variable into a 400 that names the variable.
  (The sample contexts mirror the real render contexts, so a variable the
  default template legitimately uses is never flagged; the invoice sample
  gained `unit_label` and `zev.invoice_language`, the contract sample
  `payment_terms_unit` to stay in parity.)
- **Provenance.** `PdfTemplate.default_digest` snapshots the sha256 of the
  on-disk default at save time. Migration `0009` backfills pre-existing
  overrides with the digest of the default shipping in that release — this is
  a **baseline, not a detection**: legacy rows carry no history, so an
  override saved against an older release is treated as fresh (its true
  provenance is unknowable from the stored data) and can only be flagged
  stale once a *future* release changes the default again. `is_stale` is
  computed on read — stored digest vs. the current on-disk default — and
  returned by GET/PATCH; the frontend template editor shows a banner on stale
  overrides and a hint to keep the
  `{% include "pdf/shared_pdf_base.html" %}` line. A blank digest (no
  provenance) is never flagged stale.
- **Compat preserved.** Overrides saved before the redesign (full markup,
  no include) keep rendering — pinned by a regression test; overrides that
  keep the include line get shared-base updates for free.
- **No cleanup command, deliberately.** The reviewed alternative of an
  `audit_pdf_templates` management command (classify existing overrides as
  reset-safe vs. manually-modified) is skipped: no deployment carries
  pre-redesign overrides, so there is nothing to migrate, and the `is_stale`
  banner covers the ongoing case. Add the command only if a deployment ever
  accumulates legacy overrides.

## 13. Contract issuance and versioning

The contract is no longer a throwaway render of mutable state:

- **`ContractIssue`** (`invoices.models`, migration `0010`) stores a
  frozen snapshot per issuance: `participant`, `zev`, `version`,
  `document_number`, `language`, `rendered_on` (the calendar date the document
  was rendered with — its issue date), `context_hash` (sha256 of the rendered
  HTML), the PDF bytes, `issued_at` and `issued_by`; unique on
  `(participant, version)`. `zev` is a denormalized copy of `participant.zev`
  derived in `save()` so the two can never disagree.
- **Issue-date freeze.** Change detection reproduces the stored document
  rather than re-rendering at "today": `_build_contract_context`/
  `_render_contract_html` accept an `as_of` date, and the comparison renders
  with `latest.rendered_on` + `latest.document_number`. The passing of a
  calendar day alone therefore never mints a new version (the printed issue
  date is part of the signed document); only a data/template/VAT change that
  alters the frozen document's content does.
- **Retention.** Both foreign keys are `SET_NULL`: deleting a participant or
  ZEV retains the issued snapshots as an immutable archive
  (`document_number` + the audit log keep the traceability; the retained
  `zev` column survives participant deletion). There is deliberately **no
  historical-download endpoint yet** — the API streams the latest issue only;
  earlier versions exist in the archive for future retrieval (known
  limitation).
- **`issue_contract_pdf(participant)`** renders, hashes, and either reuses
  the latest stored snapshot (unchanged content — same bytes, no new
  version) or mints a new version. `generate_contract_pdf` stays as the pure
  render for tests/previews.
- **Concurrency.** Number minting and issue creation share one transaction;
  the per-ZEV counter lock (`select_for_update`) serializes concurrent
  issuances. `latest` is re-read and re-compared under that lock — before
  minting and again after the counter bump — so a competing issuance that
  committed while this request waited is either reused (identical content
  mints **no redundant version**; the unused counter bump is an accepted
  number gap, written to the audit stream as a `contract.number_gap`
  SYSTEM event carrying the skipped and reused document numbers) or taken
  into account for the next version. A lost race can
  never collide on `(participant, version)`.
- **Document numbers** are a per-ZEV sequence `CTR-YYYY-NNNN` from
  `Zev.contract_counter` (migration `zev/0017`, atomic `F()` increment,
  `next_contract_number(year=...)`), exported in the ZEV transfer schema.
- **Download flow.** `GET /api/v1/zev/participants/{pk}/contract-pdf/`
  issues on first download and streams the snapshot afterwards; the
  filename carries the version (`contract_{last}_{first}_v{n}.pdf`). A new
  issuance writes a `contract.issue` PARTICIPANT audit event; an unchanged
  re-download writes a `contract.download` event (with
  `reused_snapshot: true`), so every receipt of the signed document is
  traceable.
- **Storage.** PDF bytes live in a `BinaryField` per snapshot (~50–400 KB
  each). Growth is proportional to participants × versions; whole-ZEV export
  (transfer archive) covers archival copies. Object storage is not in scope
  for this change.

Future work (not in this change): signature capture (place/date + upload,
later e-sign), PDF/A + PDF metadata for the 10-year retention clause, and
migrating the remaining translation dicts to gettext.