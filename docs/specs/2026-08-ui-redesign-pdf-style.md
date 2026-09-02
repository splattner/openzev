# Baseline Spec: UI redesign — print-parity design system

- Spec ID: SPEC-2026-08-ui-redesign-pdf-style
- Status: Implemented (see §14 implementation notes; Phase 0's mockup gate was dropped, §7.8)
- Scope: Major
- Type: Change
- Owners: Core maintainers
- Created: 2026-08-23
- Target Release: post-1.8.0
- Related Issues: n/a
- Related ADRs: 0014, 0015
- Impacted Areas: backend | frontend | docs
- Source audit: `b7a1b75` (2026-08-22)

---

## 1. Problem and outcome

The app and its printable documents drifted into two product languages. The web UI uses a sky-blue Mantine ramp (`#0284c7` / `#f0f9ff`→`#0c4a6e` in `frontend/src/main.tsx:29-42`) plus a hand-rolled `frontend/src/index.css` (≈43 KB, ≈211 hardcoded hexes) and a slate `#0f172a` sidebar (`index.css:92`). The PDF system in `backend/templates/pdf/shared_pdf_base.html:23-42` already had a coherent forest/ink/paper system (`--brand-deep #0d2b1d`, `--brand #143828`, `--brand-mid #1f5c3a`, `--gold #bfa05a`, etc.) shared by invoice, contract, annual statement and financial summary via a single `<style>` partial. Three styling systems (hand-rolled CSS + Mantine v9 + MUI Data Grid on two pages) coexist; chart colors live in a 2-constant `frontend/src/lib/chartTokens.ts`.

The PDF preview is structurally wrong: `POST /api/v1/invoices/invoices/preview-pdf-template/` returns HTML and `frontend/src/pages/AdminPdfTemplatesPage.tsx` does `iframe.contentDocument.write(html)`. Browsers ignore `@page`, margin boxes, `position: running(...)`, mm geometry and PDF/A XMP — the preview can never match the shipped bytes. `frontend/src/pages/InvoiceDetailPage.tsx` has no document preview at all even though `Invoice.pdf_file` / `pdf_url` stores the artifact.

**Outcome:** the app and its documents read as one family. The web UI becomes a calm, scannable operating tool (readable hierarchy, disciplined density). Tokens and brand are shared between screen and print by construction, layout grammar is not copied 1:1, and previews embed the real PDF bytes. No per-ZEV branding; one product brand for every ZEV.

The redesign is also a **simplification, not a re-theme of the same complexity**: one date-picker system (`@mui/x-date-pickers` removed in Phase 2), zero `@mui/*`/`@emotion/*` packages after Phase 5 (TanStack Table replaces the Data Grid, Mantine replaces the last MUI widgets), and a dead-rule sweep that shrinks `index.css` — the frontend ends with less styling code than it started with.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Design tokens | Single source `design/tokens.json` → generated `frontend/src/styles/tokens.css`, `styles/generatedTheme.ts` (Mantine), `lib/chartTokens.ts`, `backend/invoices/generated_chart_tokens.py` and `backend/templates/pdf/_tokens.css`; `shared_pdf_base.html` includes the generated PDF token file |
| Token semantics | Primitive layer = PDF names verbatim; semantic layer (`--app-bg`, `--surface-card`, `--border-default`, `--text-*`, `--interactive`, `--focus-ring`, `--status-*`) is what components reference; themes are maps of the same semantic names |
| Sidebar + chrome | Sidebar `#0f172a` → `--brand-deep`; active item = `--brand-pale` pill + 3px `--brand-mid` leading bar; `body` radials removed, `background: var(--surface)`; `.button` sky→green gradient removed |
| Preview fix | `preview-pdf-template` can return `application/pdf` (real WeasyPrint bytes); admin editor shows it in an `<iframe>` via object URL; invoice detail page embeds `pdf_url` in a paper frame, with contract and annual-statement embeds deferred |
| Component hygiene | Tables (sticky header, tabular-nums, right-aligned money/kWh, 36–40px rows, hover, selected=`--brand-pale`); KPI cards (≤1 dark-accent variant per view); status pills (filled desaturated, never gold-on-white, never raw text); forms/modals/toasts/empty states; standardise date pickers on Mantine |
| Page pass | Dashboard → invoices list → participants → metering/imports → tariffs → settings → admin; login = quiet paper+mark; charts everywhere consume generated chart tokens |
| Tooling | `stylelint` `color-no-hex` + `scripts/check-frontend-hex.mjs` color sweep (hex + rgb/hsl functions) in `pr-quality.yml`; Playwright before-screenshot freeze + mockups gating |
| Dependency & code reduction | Five MUI `DatePicker` call sites → Mantine and `@mui/x-date-pickers` removed (Phase 2, incl. dropping the MUI half of `DateLocaleProvider`); MUI Data Grid → TanStack Table and the last MUI widgets → Mantine, removing all `@mui/*` + `@emotion/*` packages (Phase 5, own ADR); dead-CSS sweep of `index.css` with before/after size reported |

### Out of scope

- Framework rewrite (React 19 stays).
- PDF compiler swap (WeasyPrint + PDF/A-3b `invoices/pdf_render.py` stays; Typst revisit trigger = dropping free-form HTML overrides).
- HTML facsimile of the invoice — the detail page embeds the real PDF, not a second maintained HTML view.
- Dark mode (deferred; semantic layer makes it cheap later).
- `PdfTemplate` DB override behaviour — stored full standalone HTML keeps working; overrides that inlined old hexes are flagged stale via the existing `default_digest` mechanism.
- Per-ZEV branding — no per-ZEV logo/color, no ramp derivation, no tenant theme switcher. One brand for every ZEV (explicit follow-up if ever wanted).
- New UI library. No new MUI outside the two Data Grid pages.

---

## 3. Actors, permissions, and ZEV scope

No new roles. The redesign is visual and does not change authorization.

| Actor | Preview (HTML or PDF) | Template write/reset | Invoice/contract PDF embed |
|---|---|---|---|
| `admin` | `POST /invoices/invoices/preview-pdf-template/` (sample data, no tenant scope) | `GET/PATCH/DELETE /invoices/invoices/{pdf,contract-pdf,annual-statement-pdf}-template/` — `IsAdmin` (`views_templates.py:_AdminTemplateView`) | Can open any invoice/contract PDF (`pdf_url` / `contract-pdf/` stream) across all ZEVs |
| `zev_owner` | No | No (403) | Own ZEV invoices/contracts only (existing `IsZevOwnerOrAdmin` + object checks) |
| `participant` | No | No | Own invoices/contracts only |
| `guest` | No | No | No |

`preview-pdf-template` is intentionally tenant-free: it renders the three sample contexts from `invoices/template_context.py` (`build_sample_invoice_context`, `build_sample_contract_context`, `build_sample_annual_statement_context`) so there is no ZEV scoping to enforce.

---

## 4. Data model and file model

No Django model or DB migration. The "model" is the token source file and its generated outputs.

### 4.1 `design/tokens.json` (single source of truth)

**File:** `design/tokens.json` (new; JSON; committed).

Top-level keys:

| Key | Value | Notes |
|---|---|---|
| `primitives` | `object` | PDF names verbatim, plus `--white` and the desaturated status fills (`--neutral-100` `#e2e8f0`, `--info-100` `#e0f2fe`, `--success-100` `#dcfce7`, `--danger-100` `#fee2e2`, `--warning-100` `#fef9c3` — the existing `.badge-*` families) — the only place hex literals may live |
| `semantics` | `object` | Alias map `semanticName → primitiveName` (e.g. `"--app-bg": "var(--surface)"`). Components reference semantics only. |
| `themes` | `object<string, object>` | The default theme is expressed by `semantics` directly (emitted as `:root`). `themes` holds only *alternate* maps (`paper-light`, `high-contrast`, etc.) once one ships — deferred until a tested use case exists. Adding a theme is a token-file change only (pure data: reassignment of the same semantic names to primitives/ramp steps; no component code branches). |
| `charts` | `object` | Mirrors `invoices/pdf_charts.py:7-18` 1:1 (see §4.3) |
| `type` | `object` | Font families for screen (`Inter Variable`) and print (`Helvetica Neue`). Additional scale/tracking/numeric-policy properties are deferred until they are consumed by generated outputs.

The schema is purpose-built (no external token framework). DTCG 2025.10 (`.tokens.json`, `$value`/`$type` groups) is the recognized standard and the migration target **if** a design-tool pipeline (Figma Variables, Style Dictionary) ever enters the workflow — not adopted now: there is no design-tool consumer today and the generator stays dependency-free. The primitive → semantic-alias → theme structure already maps 1:1 onto DTCG concepts.

`primitives` verbatim (from `shared_pdf_base.html:23-42`):

```json
{
  "primitives": {
    "--brand": "#143828",
    "--brand-accent": "#9ec3ac",
    "--brand-deep": "#0d2b1d",
    "--brand-glow": "#d4e0d7",
    "--brand-ink": "#091a14",
    "--brand-light": "#d6ead9",
    "--brand-mid": "#1f5c3a",
    "--brand-muted": "#c8dccf",
    "--brand-pale": "#e8f0ec",
    "--chart-surface": "#fbfcfb",
    "--danger-100": "#fee2e2",
    "--danger-300": "#fecaca",
    "--danger-600": "#dc2626",
    "--danger-700": "#b91c1c",
    "--gold": "#bfa05a",
    "--info-100": "#e0f2fe",
    "--info-200": "#bae6fd",
    "--ink": "#0f172a",
    "--ink-soft": "#334155",
    "--line": "#e2e8f0",
    "--line-subtle": "#f1f5f9",
    "--muted": "#64748b",
    "--neutral-100": "#e2e8f0",
    "--subtotal-color": "#24352c",
    "--success-100": "#dcfce7",
    "--success-200": "#bbf7d0",
    "--success-600": "#15803d",
    "--success-700": "#166534",
    "--surface": "#f8faf7",
    "--violet-200": "#ddd6fe",
    "--warning-100": "#fef9c3",
    "--warning-200": "#fde68a",
    "--warning-300": "#fde047",
    "--warning-800": "#854d0e",
    "--white": "#ffffff",
    "--zebra": "#f3f6f2"
  }
}
```

Semantic examples (final map decided in Phase 0; names below are normative):

- `--app-bg` → `var(--surface)` (replaces `index.css:4 #f8fafc` + sky radials `index.css:25-28`)
- `--surface-card` → `var(--white)` with `border: var(--line)` (replaces `card`/`table-card` `rgba(255,255,255,0.9)` / `rgba(148,163,184,0.2)`); semantics always alias primitives — never raw hex
- `--text-primary` → `var(--ink)`; `--text-body` → `var(--ink-soft)`; `--text-muted` → `var(--muted)`
- `--border-default` → `var(--line)`; `--border-subtle` → `var(--line-subtle)`
- `--interactive` → `var(--brand-mid)`; `--interactive-hover` → `var(--brand)`; `--focus-ring` → `var(--brand-mid)` 2px / 2px offset
- `--status-draft/open/paid/overdue/cancelled` + `--status-neutral/info/success/warning/danger` for `.badge-*` remap (desaturated fills, never gold-on-white)
- `--sidebar-bg` → `var(--brand-deep)`; `--sidebar-active` → `var(--brand-pale)`

No raw hex may appear outside `design/tokens.json` and its generated outputs, and neither may raw `rgb()/rgba()/hsl()/hsla()` function literals — the original hex-only sweep missed an `rgba(0, 102, 204, …)` legacy sky-blue in the template editor, so the sweep now covers color functions too. Enforcement is split by surface: `stylelint` `color-no-hex` covers `frontend/src/**/*.css` (only the generated `frontend/src/styles/tokens.css` is allowlisted); hand-written TSX is enforced by the `scripts/check-frontend-hex.mjs` color sweep, which also walks the backend PDF/HTML templates and `invoices` Python (generated outputs, tests, and migrations exempt). The sweep's allowlist (`scripts/hex-migration-allowlist.json`) supports per-file `"path@alpha"` entries that sanction *neutral alpha scrims/shadows only* (`rgba()`/`hsla()` white/black/slate fades in `index.css`, the overlay modals, and the invoice/contract dark headers); hex and opaque `rgb()`/`hsl()` are never allowlistable. The JSON source is enforced by `node scripts/generate-tokens.mjs --check` + the idempotence test — JSON is not CSS and never sits in a stylelint allowlist.

### 4.2 Generated outputs (committed, produced by `scripts/generate-tokens.mjs`)

All five are pure derivations; hand-editing them is a lint/test error.

| File | Consumes | Consumed by |
|---|---|---|
| `frontend/src/styles/tokens.css` | `primitives + semantics + themes` → `:root` map (alternate `[data-theme]` maps only when a second theme ships) | Imported in `frontend/src/main.tsx` before `index.css`; every component uses `var(--semantic)` |
| `frontend/src/styles/generatedTheme.ts` | Mantine theme object: `primitives.brand` ramp + semantics (`primaryColor: "brand"`, `primaryShade: 6`, `fontFamily` sync with `index.css:2`) — replaces sky ramp `#f0f9ff … #0c4a6e` | Imported by `MantineProvider` in `main.tsx`; the entrypoint stays hand-written — generated code lives only in visibly generated files |
| `frontend/src/lib/chartTokens.ts` | `charts` block, emitted as **resolved literal strings** (Recharts props and SVG `fill="…"` need real color values; they do not resolve `var(--…)`) | `DashboardPage`, `MeteringChartPage`, `TariffPriceHistoryChart`, feasibility charts, `EnergyFlowChart`, `RawMeteringTable` (recharts) |
| `backend/invoices/generated_chart_tokens.py` | `charts` block as plain Python constants (same literals as `chartTokens.ts`) | imported by `invoices/pdf_charts.py` and `invoices/annual_statement.py` (its SVG chart) — no duplicated color literals in Python |
| `backend/templates/pdf/_tokens.css` | `primitives` (same block as `shared_pdf_base.html:23-42`) | `{% include "pdf/_tokens.css" %}` from `shared_pdf_base.html` (or an equivalent `_tokens.html` partial) — the PDF stays the source of the same hex values; no hex drift between screen and print |

`scripts/generate-tokens.mjs` (new, no deps): reads `tokens.json`, validates its schema (required keys; semantics reference existing primitives; hex literals only inside `primitives`), enforces strictly decreasing WCAG 2.1 relative luminance across the 10-step brand ramp (`--brand-pale` → `--brand-ink`) in both generate and `--check` modes, and emits the five files deterministically. A unit test `design/tokens.test.mjs` asserts that regenerating and diffing produces no changes (parity by construction), and a negative test runs the generator against a temp tree with the historical `--brand-glow` ↔ `--brand-muted` inversion (plus an equal-luminance tie) and asserts non-zero exit with the actionable inversion message in both generate and `--check` modes.

### 4.3 Chart token parity

`design/tokens.json:charts` is the PDF palette source — the generator emits it as `backend/invoices/generated_chart_tokens.py`, from which `pdf_charts.py` imports the constants (values below):

```python
_CHART_LOCAL = "#1f5c3a"   # = --brand-mid
_CHART_GRID  = "#c9891a"
_CHART_INK   = "#0f172a"   # = --ink
_CHART_MUTED = "#64748b"   # = --muted
_CHART_GRIDLINE = "#e8edeb"
_CHART_AXIS  = "#94a3b8"
_CHART_BG    = "#fbfcfb"   # = --chart-surface
_CHART_LABEL = "#334155"   # = --ink-soft
_FLOW_LOCAL_CONS = "#0e7490"
_FLOW_GRID_EXP   = "#7c3aed"
PROD_COLORS  = ["#1f5c3a", "#2f7a4d", "#15803d", "#0f766e", ...]
CONS_COLORS  = ["#1d4ed8", "#2563eb", "#1e40af", ...]
_CHART_LABEL_ON_FILL = "#fff"   # = charts.labelOnFill — on-bar white labels
```

`design/tokens.json:charts` mirrors this 1:1 (same hexes, same role names) and is the SSOT: the generator emits `backend/invoices/generated_chart_tokens.py`, and `pdf_charts.py` imports its constants from it — no duplicated color literals remain in Python, and drift between `pdf_charts.py` and `tokens.json` becomes a `--check`/idempotence failure. `frontend/src/lib/chartTokens.ts` currently holds only `AXIS_COLOR / ANNOTATION_COLOR`; after generation it re-exports the full map as **resolved literal strings** (`export const CHART_LOCAL = "#1f5c3a"` — Recharts props and SVG `fill="…"` do not resolve `var(…)`), so recharts and the PDF SVG share one map. Hand-written companion `frontend/src/lib/chartTheme.tsx` centralizes the recharts config *shapes* shared by the feasibility charts (axis tick typography, bottom-axis/CHF y-axis labels, tooltip card, legend swatch) on top of those literals — it is not generated and holds no colors of its own.

The annual-statement SVG chart and two `pdf_charts.py` accents previously carried pre-redesign literals (`#4caf50`, `#90a4ae`, `#888`, `#eee`, `#666`, `#fff`, `#eef5f0`). Nothing is in production, so they were remapped onto the shared palette instead of being frozen: ZEV/grid bar portions use `_CHART_LOCAL`/`_CHART_GRID` (the same local/grid pair as every other PDF chart), y-axis ticks `_CHART_MUTED`, month/legend labels `_CHART_LABEL`, gridlines and the metering daylight band `_CHART_GRIDLINE`, and on-bar white labels the `charts.labelOnFill` entry (`#fff`, emitted to the Python module; the screen-side TS emitter omits it — no screen chart currently paints on-bar labels). The legacy HTML templates were swept in the same pass: `annual_statement_pdf.html` and `financial_summary_pdf.html` now include `pdf/_tokens.css` and reference `var(--…)` — their `#2c5f2e` chrome became `--brand-mid` accents on `--brand-deep` dark table headers (white header text, matching the invoice's line-items treatment), the grey ladder collapsed onto `--ink`/`--ink-soft`/`--muted`/`--line`/`--line-subtle`, and `#f0f9f0` highlight washes became `--brand-pale`; the invoice/contract white fills use `var(--white)`. No pre-redesign colour value is retained anywhere outside `design/tokens.json` and its five generated outputs. The one sanctioned exception: neutral alpha scrims/shadows (white/black/slate `rgba()` fades in `index.css`, the overlay modals, and the invoice/contract dark headers) stay raw, allowlisted per file via `"path@alpha"` entries in `scripts/hex-migration-allowlist.json` — the sweep still rejects hex and opaque `rgb()`/`hsl()` in those files (see §5.1 enforcement).

### 4.4 `index.css` contracts retained

The existing management-page contracts from `2026-04-frontend-management-page-design.md:100-112` (`.page-stack`, `.card/.table-card/.stat-card`, `.button*`, `.badge-*`, `.actions-row*`, `.participant-*/.metering-*/.tariff-*/.invoice-*`) remain the design system. This change re-skins them (values → `var(--semantic)`) and does not introduce a second component library.

### 4.5 Deleted

- `frontend/src/App.css` — unreferenced Vite scaffolding (git-tracked but imported nowhere in the bundle); delete in Phase 2.

---

## 5. Design philosophy (binding constraints on the implementation)

### 5.1 The PDF is a sibling, not the parent

The PDF language is an excellent print system and a mediocre spec for a dense billing app. Copying it verbatim onto CRUD pages produces worse scanability (uppercase + tracking everywhere), a flat brochure-like admin, motif overuse (gradient cards on every button), and drift between two maintained "invoice views".

**Share tokens, brand and chart palette. Do not share layout grammar 1:1.**

| Keep from the PDF | Do NOT copy to screen | Improve on both |
|---|---|---|
| Forest/ink/paper palette (`--brand*`, `--ink*`, `--surface`, `--zebra`) | 9.5pt / Helvetica print scale — screen stays `Inter Variable` (`index.css:2`, `main.tsx:25`) at functional sizes | Type hierarchy: page title 1.5–1.75rem/650/−0.02em + one-line description; labels 0.75–0.8125rem/500; uppercase only for true section kickers via `text-transform`, never in translation strings |
| Tabular numerals for CHF/kWh (`font-variant-numeric: tabular-nums`) | Uppercase `.eyebrow` on every field label | Fewer boxes: one card surface, more whitespace, radius 8/10px, shadows only on overlays |
| One accent (gold *or* mid-green), once per view | `.amount-card` gradient + `.amount-card-shine` circle repeated as button chrome (`invoice_pdf.html:91-113`; the contract analogue is `.tariff-card`/`.tariff-card-shine` at `contract_pdf.html:122-144` — the contract template has no `.amount-card`) | Tables: sticky header, right-aligned quantities/money, 36–40px rows, hover, selected = `var(--brand-pale)` |
| Dark-header hairline tables (`line-items thead th` `var(--brand-deep)`) | `document-header` anatomy as page chrome for Imports/Tariffs/Admin | Status: small filled desaturated pills (`.badge-*` remapped), never raw text |
| Shared chart palette (PDF ≡ dashboard) | Brand dots / accent bars / shine circles as recurring chrome | Dashboard: one hero number + 3–4 KPIs + one energy-flow + short exception list |
| Paper + ink calm (`--surface #f8faf7`, `--ink #0f172a`) | | Login: quiet paper + brand mark (no gradient circus) |

### 5.2 Gold usage (WCAG AA)

`--gold #bfa05a` on white `#fff` is contrast `~2.8:1`. WCAG AA requires `4.5:1` for normal text (`3:1` for large/bold ≥18pt/14pt-bold) — gold-on-white **fails** and would block the Phase 4 contrast audit. The PDF already obeys this: gold is only `savings-row.highlight .savings-value` on `var(--brand-deep)` at `9pt/900` inside `.amount-card` (`invoice_pdf.html:180-184`). Binding rule:

- `--gold` is decorative/display only. Permitted on `var(--brand-deep)` / `var(--brand)` at `≥16pt` or `≥14pt/700`, or as 1–2px accent bars/dots that are not text.
- Never as text color on `#fff` / `var(--surface)` / `var(--brand-pale)` / `var(--zebra)`. Status pills in dense tables use desaturated fills (`--brand-pale`, `var(--success-100)`, `var(--danger-100)`, etc. — status hexes live in `primitives`, §4.1) with `--ink-soft` text — the same rule the PDF follows.
- Manual axe-core / browser contrast check in Phase 4 must pass at AA+ (see §9).

### 5.3 Screen quality bar (review checklist on every PR)

- Page title + description; toolbar = filters left, primary action right, no second card wrapper.
- Sidebar `var(--brand-deep)`; active item = `var(--brand-pale)` pill + 3px `var(--brand-mid)` leading bar (functional, not a decorative dot).
- Focus: `2px solid var(--focus-ring)` / `2px` offset, everywhere — including Mantine widgets (`DatePickerInput`, `Menu`, `Switch`) via global `:focus-visible` + Mantine `focusRing`.
- Readability > "premium": for a Swiss billing tool, clear > ornamental.

---

## 6. API contracts

### 6.1 PDF template preview — PDF output (admin-only)

**Endpoint:** `POST /api/v1/invoices/invoices/preview-pdf-template/` — `PdfTemplatePreviewView` (`invoices/views_templates.py:229`, `permission_classes=[IsAdmin]` via `_AdminTemplateView`). Audit behaviour: the mutation endpoints (`PdfTemplateView` PATCH/DELETE) are audit-logged and DENIED-log non-admin 403s via `denial_audit`; the preview endpoint is stateless and does not override `denial_audit`, so neither its successes nor its 403s are audit-logged — unchanged by this spec.

Today the view renders the submitted `content` with a sample context and returns `{ html }`. This change keeps HTML as a debug toggle and adds real PDF output:

| Field | Type | Notes |
|---|---|---|
| `content` | `string` | Required, non-blank — blank/whitespace → `400 {"error": "Template content is required."}`. Capped at `MAX_TEMPLATE_CHARS` (500 000 chars) on **both** the preview and the `PATCH` save path — oversized → `400 {"error": "Template content exceeds the …-character cap."}` — so a pasted megabyte-scale document cannot pin a WeasyPrint worker at preview time, or later at document/email render time once stored. Preview renders **non-strict** (`views_templates.py:81` — "preview stays non-strict so admins can type in progress"): syntax errors reject with `400 {"error": "Template rendering error: …"}`, unknown *output* variables render empty. The `strict-validation` engine + `string_if_invalid` sentinel rejection (with its documented limitation that variables consulted only in `{% if %}/{% for %}` control flow are not detected) applies at `PATCH` save time only. |
| `template_type` | `"invoice" \| "contract" \| "annual_statement"` | Default `invoice`. Selects the sample context builder in `invoices/template_context.py`: `build_sample_invoice_context()` / `build_sample_contract_context()` / `build_sample_annual_statement_context()`. Unknown values → `400 {"error": "Unsupported template type."}` — the preview validates the body-supplied type; the PATCH save path keeps the helper's invoice fallback (its `template_type` arrives from fixed URL routes). |
| `output` | `"html" \| "pdf"` | Default `html` for backwards compat; `pdf` requests real bytes. Also accepted as `?output=pdf` query param — either form selects PDF output. (The specced-elsewhere `?format=pdf` spelling is unavailable here: DRF's `URL_FORMAT_OVERRIDE` content negotiation intercepts unknown `format` values with a 404 before the view dispatches.) |

**Behaviour:**

- Resolve sample context for `template_type` (same helpers the existing preview and `PdfTemplateView` validation already use; invoice sample already gained `unit_label` and `zev.invoice_language`, contract sample `payment_terms_unit` so no variable is falsely flagged unknown — see `2026-08-contract-pdf-redesign.md:604`).
- Render: `Template(content).render(Context(sampleContext))` via `_render_with_sample_context` (`views_templates.py:68`, non-strict). Unlike `invoices/pdf.py:_render_template` there is no `render_to_string` fallback — preview content is a complete template body, not an include-bearing partial. The contract sample context sets `is_preview: True` (`template_context.py:191`) so `{% if is_preview %}` placeholder prose (`local_tariff_note_placeholder`, `additional_placeholder`) renders in contract preview but never on issued documents; the invoice and annual-statement sample contexts do not set the flag today.
- If `output == "html"`: return existing shape `200 { html }` (unchanged; debug mode). The frontend renders debug HTML as **escaped source text** — it is never written into an iframe or executed. (`iframe.contentDocument.write` of server-rendered admin HTML is a same-origin script-execution footgun even admin-only: a template pasted from elsewhere could run script in the app origin.) Render errors → `400 { error: "Template rendering error: …" }`; blank content → `400`.
- If `output == "pdf"`: pipe the rendered HTML through the existing `invoices/pdf_render.py:render_pdf(html)` (WeasyPrint → PDF/A-3b, XMP `pdfaid` + sRGB OutputIntent + font subsets, same helper contract/financial-summary already use). Return `200` with `Content-Type: application/pdf`, `Content-Disposition: inline; filename="preview-{template_type}.pdf"`. Template-level failures (syntax errors, unrenderable input) → `400 { error }` (same error surface as HTML mode); unexpected renderer/infrastructure failures → `500 {"error": "PDF rendering failed."}` — deliberately generic (WeasyPrint exceptions can carry server paths); the full traceback goes to the log via `logger.exception`. Preview content is capped at a documented maximum size (oversized → `400`) to bound WeasyPrint work. No `PdfTemplate` row is written — preview is stateless.
- No tenant or ZEV scoping — sample data is synthetic.
- Parity ≠ byte-equality: sample contexts, timestamps and generated IDs differ from issued documents. The guarantee is the same rendering pipeline, template version, token output and PDF profile — the preview is visually and structurally representative of the issued document.
- Server-side fetch policy: `render_pdf` passes WeasyPrint a `URLFetcher` restricted to `data:` URIs (`invoices/pdf_render.py:ALLOWED_URL_PROTOCOLS`). Every shipped template is fully inline (inline CSS, inline SVG, zero external references; the PDF/A ICC profile ships inside the weasyprint package and bypasses the fetcher), so document rendering needs no other protocol. Local-file reads (explicit `file:` URLs, and relative URLs resolved against `base_url`) and outbound http/https/ftp from admin-editable template content are denied on **both** the preview and the issued-document paths — WeasyPrint fetching is an SSRF/local-file-exposure consideration even on an admin-only surface. A rejected resource degrades like a missing one: WeasyPrint logs it and renders without it.

**Frontend consumer:** `frontend/src/lib/api/invoices.ts:previewPdfTemplateBlob(content, templateType, signal?)` — blob fetch posting `output:"pdf"` with `Accept: application/pdf` (when a client sends `Accept: application/pdf`, the view falls back to its default renderer instead of answering 406, since the success payload is opaque bytes produced outside DRF renderers); `AdminPdfTemplatesPage.tsx` renders the blob as an object-URL `<iframe title="PDF preview">` (native viewer gives A4 pagination/fidelity for free). Debounced 700 ms auto-render via one shared `renderPreview(source)` callback that owns the revision counter (discards out-of-order responses) and the `AbortController` (cancels superseded requests — a slow WeasyPrint render can otherwise finish after a newer one). Auto-render fires whenever the preview view is visible and content changes; because editor and preview are mutually exclusive views, typing never renders — in practice this is one render on entering the preview and one after each editor round-trip, and it applies to every template size (the backend preview cap bounds pathological content). The last object URL stays visible with a transient "re-rendering…" state; the previous URL is revoked only after the replacement frame has loaded, and on unmount. An HTML/source toggle stays for debugging pasted snippets — displayed as escaped text, never executed; an explicit render button remains for manual re-renders.

**View name:** `PdfTemplatePreviewView` (existing). Permission and audit behaviour unchanged. No new URL — same path, new output mode.

### 6.2 Invoice detail — embed the real PDF

No new backend endpoint required, but the frontend behaviour is specified here because it is the "looks like the PDF" guarantee:

- `frontend/src/pages/InvoiceDetailPage.tsx` — after loading `GET /api/v1/invoices/invoices/{id}/`, read `invoice.pdf_url` (from `InvoiceSerializer.pdf_url` / `Invoice.pdf_file` `FileField` `invoices/pdf/invoice_{number}.pdf`). If `pdf_url` is present, render:
  - operational chrome **above** a paper-style frame: page header (invoice number title, participant/period subtitle, back link), a `grid-4` card row (status pill from the `invoice.status.*` i18n namespace — there is no `status_display` field on `InvoiceSerializer` or the `Invoice` TS type — plus total/subtotal/VAT CHF cards), and an energy-totals card (local/grid/feed-in kWh), then
  - the blob-fetched artifact in an `<iframe src={objectUrl}>` inside `class="pdf-frame"` (`border: 1px solid var(--line)`, `border-radius: 8px`, `background: var(--surface)`), with `PdfPreview`'s download/open-in-new-tab fallback. All document embeds fetch authenticated blobs (invoice `pdf_url`, contract, annual statement) and render object URLs — uniform across cookie- and token-based auth (an iframe `src` cannot attach an `Authorization` header) and across `Content-Disposition` values; the iframe never navigates to API URLs directly, so CSP `frame-src` stays closed. Verify Chrome/Firefox/Safari; revoke the previous object URL only after the replacement frame has loaded.
- If `pdf_url` is null (rare — invoice created but `generate_pdf` not yet run), show a "Generate PDF" affordance that calls the existing `POST /api/v1/invoices/invoices/{id}/generate-pdf/` (`IsZevOwnerOrAdmin`, returns `{ pdf_url }`) and then embeds the result. No new generate-if-missing endpoint — reuse the existing action.
- This is a restructure, not a facsimile: no second HTML rendering of line items in the detail page that would drift from the PDF (rejected alternative §11).

> **Deferred:** embedding the real PDF on contract detail (`GET /api/v1/zev/participants/{pk}/contract-pdf/`) and on the annual-statement download page was specced but not yet implemented in this branch — those pages continue to serve the existing views. `PdfPreview` is used on `InvoiceDetailPage` and `AdminPdfTemplatesPage` only.

### 6.3 New endpoint: authenticated PDF download

`GET /api/v1/invoices/invoices/{id}/pdf/` (``InvoiceViewSet.download_pdf``).
Returns the stored PDF artifact via ``FileResponse`` (``Content-Type: application/pdf``).
Permission: ``IsAuthenticated``; scoping is enforced by the invoice's queryset
(owner/participant only, via ``scope_queryset``). Returns 404 if no ``pdf_file``
is stored or the user is out of scope; 401 for anonymous.

See also: ``frontend/src/lib/api/invoices.ts`` ``fetchInvoicePdfBlob()``.

`PdfTemplate` CRUD (`GET/PATCH/DELETE` per template name), `valid_from/valid_to` ZEV settings, and `AppSettings.load().date_format_short` (used by both `_build_template_context` and the contract context via `invoices/dates.py:format_date_value`) are unchanged. Template save-time validation and `is_stale` (`default_digest` sha256, migration `invoices/0009`) already shipped and stay as-is.

---

## 7. Frontend

### 7.1 Approach

Re-skin in place; no new UI library; one token sweep. Existing contracts from `2026-04-frontend-management-page-design.md` (`.button`, `.badge-*`, `.card`, `.page-stack`, `StatCard`, `ActionMenu`, `FormModal`) are extended, not duplicated. No new MUI outside the two Data Grid pages; dates/comboboxes/overlays = Mantine (`DatePickerInput`, `Popover`, `DatesProvider`).

### 7.2 Token sweep

**Files first touched (Phase 1):**

- `frontend/src/main.tsx:24-43` — replace sky ramp (`#f0f9ff`→`#0c4a6e`, `primaryShade:6`, `primaryColor:"brand"` sky) with brand ramp derived from tokens (`--brand-deep` base, `--brand-mid` interactive, `--brand-pale` hover). Update sync comment re `fontFamily` (`Inter Variable` stays on screen; `Helvetica Neue` stays PDF-only).
- `frontend/src/index.css` — full tokenisation:
  - `:root` `background: #f8fafc` (`index.css:4`) + `body` radials (`index.css:25-28` sky+green) → `background: var(--app-bg)` (`--surface #f8faf7`).
  - `.sidebar` `background #0f172a` (`index.css:92`) → `var(--sidebar-bg)` (`--brand-deep #0d2b1d`).
  - `.eyebrow #38bdf8` (`index.css:186`) → `var(--text-muted)` (`--muted #64748b`) or brand-mid where on-dark needs it; uppercase + `0.08em` only on true section kickers, not every form label.
  - `.button` sky→green gradient (`index.css:1041` `#0284c7→#16a34a`) → `background: var(--interactive)` flat (with hover `var(--interactive-hover)`); retain `.button-secondary/.button-danger/.button-compact` as semantic but remapped to tokens.
  - `.card/.table-card/.stat-card` `rgba(255,255,255,0.9)` + `rgba(148,163,184,0.2)` → `var(--surface-card)` + `var(--border-default)`; collapse double border+shadow on section cards.
  - `.badge-*` remap (`index.css:979-1019` `#e2e8f0`/`#e0f2fe`/`#dcfce7`/`#fee2e2`/`#fef9c3` families) → `--brand-pale`/`--status-*` semantics (filled desaturated, `font-weight:700`, never gold-on-white).
  - `.page-stack th` / `.raw-metering-*` header treatments → `var(--surface-card)` / `var(--border-default)` / `--brand-deep` dark-header variant only for document-like tables.
  - Global `:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px }` (covers Mantine + MUI).
  - Inputs/selects `border #cbd5e1` / `background #fff` → `var(--border-default)` / `var(--surface-card)`; errors stay `#fee2e2/#991b1b` but derived via semantics.

A `rg --pcre2 '#[0-9a-fA-F]{3,8}\b' frontend/src` inventory is committed as a Phase 0 grep table in this spec's PR description, mapping each hex → semantic (not as a repo file). `stylelint` (next) prevents new hexes from Phase 1 onward.

### 7.3 Typography

- App keeps `Inter Variable` (`index.css:2`, `main.tsx:25`). PDF keeps `Helvetica Neue, Helvetica, Arial` (`shared_pdf_base.html:51` `9.5pt`). Do not unify.
- Hierarchy: page title `1.5–1.75rem / 650 / -0.02em` + one-line description; section kicker `0.75rem / 700 / 0.08em / uppercase` via `text-transform`; body `0.875–1rem / 400`; labels `0.75–0.8125rem / 500`. `tabular-nums` only on CHF/kWh/money/quantities (`td.numeric`, `savings-value`, `kpi-value`, `raw-metering-num`).

### 7.4 Tables

- Plain tables (`.page-stack table`) + the shared `frontend/src/components/DataTable.tsx` (TanStack) styled by the `.data-table` CSS contract (sticky header, `td.numeric`, hover). The planned bridging module `frontend/src/lib/dataGridTheme.ts` was never needed — MUI was retired in one sweep rather than re-themed first.
- Sticky `thead`, `36–40px` rows, `1px solid var(--border-default)` separators, `hover: var(--surface)`, `selected: var(--brand-pale)`; quantities/money `text-align:right` + `tabular-nums`; header `background: var(--brand-deep)` only for invoice-like dense billing tables (participants/metering keep light headers). Zebra `var(--zebra)` optional (documents keep it; UI uses it only where scans benefit).

### 7.5 Cards and chrome

- KPI cards: `StatCard` (`frontend/src/components/StatCard.tsx`) plus `KpiCard` patterns on insights — one dark accent variant max per view (`kpi-card--accent` `var(--brand-deep)`/`--brand-accent` on dark). No gradient shine circles on buttons.
- Login (`frontend/src/pages/LoginPage.tsx`): quiet `var(--surface)` paper + centred brand mark + `var(--brand-deep)` primary action; remove gradient.

### 7.6 Date pickers

Standardise on Mantine (`DatePickerInput` + `DatesProvider`). In Phase 2, cut over the five existing `@mui/x-date-pickers:DatePicker` call sites (`ZevGeneralSettingsFields`, `AdminVatSettingsPage`, `TariffFormModal`, `MeteringAssignmentFormModal`, `TariffVersionModal`) to Mantine `DatePickerInput`; reduce `DateLocaleProvider` to its Mantine `DatesProvider` half (drop `LocalizationProvider`, `AdapterDayjs`, and the MUI `localeText` maps); and remove the `@mui/x-date-pickers` dependency — one date-picker system instead of two, net dependency reduction. This is a data-contract migration, not a cosmetic swap: every picker must keep submitting and displaying the same plain civil dates in the existing format (ADR 0007 UTC-storage/civil-display) with no `Date`-object round-trip that shifts timezones; per-picker tests assert the submitted format is unchanged.

### 7.7 PdfPreview component

**File:** `frontend/src/components/PdfPreview.tsx` (new, ~43 LOC).

```tsx
interface PdfPreviewProps {
  src: string | null        // object URL — all callers blob-fetch (auth- and disposition-safe)
  title?: string
  height?: string           // default "72vh"
}
```

- Renders `<iframe src={src} title={title} style={{width:"100%",height}} />` inside the `.pdf-frame` wrapper class (`border:1px solid var(--border-default); border-radius:8px; background:var(--surface)`); a permanent "Open in new tab" fallback link is shown below the frame.
- Caller owns the authenticated fetch+revoke: `useEffect` that `URL.createObjectURL(blob)`; revoke the previous URL only after the replacement frame has loaded, and `return () => URL.revokeObjectURL(url)` on unmount.

### 7.8 Code-only mockups (Phase 0 gate — dropped in practice)

The planned dev-only mockup routes `frontend/src/pages/design/PreviewDashboard.tsx` / `PreviewInvoiceDetail.tsx` / `PreviewCrudPage.tsx` were never created: the token sweep went straight onto the live pages, and the regenerated user-guide screenshots (Phase 4) served as the acceptance artefacts instead. The remaining Phase 0 references in this spec read as history, not inventory.

### 7.9 Routes and query keys

| Page | File | Route | Query key | Mutation |
|---|---|---|---|---|
| Dashboard | `frontend/src/pages/DashboardPage.tsx` | `/` (`index` under `Layout`) | `queryKeys.metering.dashboardSummary({…})` + `queryKeys.invoices.list(zevId)` + `queryKeys.metering.hourlyProfile(…)` | none — read-only: KPI (ZEV-wide) → energy-flow → open-invoices exception list → charts. Header eyebrow is the selected ZEV name scope line (blank with no ZEV selected); no document-download controls (those live on Reports). |
| Reports | `frontend/src/pages/ReportsPage.tsx` | `/reports` | none (mutations only) | `downloadAnnualStatement({year})` (participant single PDF), `downloadAllAnnualStatements({year, zev_id})` (admin/owner ZIP), `downloadFinancialSummary({year, zev_id?})` — `zev_id` for admin/owner, omitted for participant (backend scopes by participant). Role branches mirror the former dashboard: admin/owner ZIP + financial summary; participant single PDF + financial summary. Layout: ZEV-name header eyebrow (admin/owner only), one shared year selector (`aria-label`, no visible label, disabled while a download is pending, defaults to the last completed year, recomputed per render), two `YearDownloadCard`s in a `grid grid-2` (icon+text download buttons, `role="alert"` error line styled by `.error-text`), `ReportsEmptyState` guard distinguishing no-ZEV (`pages.reports.noZev*`) from stale/no selection (`pages.reports.selectZev*`). |
| Invoices list | `frontend/src/pages/InvoicesPage.tsx` | `/invoices` | `queryKeys.invoices.periodOverview(...)` = `['invoices', 'period-overview', zevId, periodStart, periodEnd]` (`queryKeys.ts:27-28`) | `generate/approve-all/send-all` invalidates period-overview |
| Invoice detail | `frontend/src/pages/InvoiceDetailPage.tsx` | `/invoices/:invoiceId` (`App.tsx:182`) | `queryKeys.invoices.detail(invoiceId)` = `['invoices', 'detail', invoiceId]` (`queryKeys.ts:25`) | `generate-pdf` → set `pdf_url`; embed `PdfPreview src={pdfUrl}` |
| Template editor | `frontend/src/pages/AdminPdfTemplatesPage.tsx` | `/admin/pdf-templates` | `queryKeys.admin.invoicePdfTemplate()` / `.contractPdfTemplate()` / `.annualStatementPdfTemplate()` = `['admin', 'pdf-template', <type>]` (`queryKeys.ts`) | `previewPdfTemplateBlob` debounced → object URL |
| Participants etc. | existing | existing | existing | existing — re-skin only |

### 7.10 TypeScript types

No new API response shape besides the `output` param and the authenticated ``GET …/pdf/`` blob endpoint (see §6.3). The existing `frontend/src/types/api.ts` types `PdfTemplateResponse` (`template_name`, `content`, `is_customized`, `is_stale`, `detail?`) and `InvoiceSerializer.pdf_url` are unchanged. `PdfPreviewProps` (above) lives in `frontend/src/components/PdfPreview.tsx`, not in `types/api.ts`.

### 7.11 API client

**File:** `frontend/src/lib/api/invoices.ts`

| Function | Method | Endpoint | Change |
|---|---|---|---|
| `previewPdfTemplateBlob(content, templateType, signal?)` | POST | `/invoices/invoices/preview-pdf-template/` | Posts `output:"pdf"` in the body with `responseType:"blob"` + `Accept: application/pdf`; the endpoint itself also accepts `output:"html"` (JSON `{html}`) and `?output=pdf` |
| `fetchInvoicePdfBlob(invoiceId, signal?)` | GET | ``/invoices/invoices/{id}/pdf/`` | Authenticated blob fetch via axios client (auth + 401 refresh); replaces same-origin ``/media/`` fetches that break when ``DEBUG=False`` drops ``static()`` media serving |
| `generateInvoicePdf(id)` | POST | `/invoices/invoices/{id}/generate-pdf/` | reused by detail page when `pdf_url` is null |

---

## 8. Shared PDF design language (binding reference)

This is the anchor the UI shares, not a spec to copy verbatim (see §5.1). The PDF tokens and anatomy already shipped in `2026-08-contract-pdf-redesign.md`; this spec makes the UI stay in family with them.

**Source of tokens:** `design/tokens.json` (SSOT). The PDF side consumes the generated `backend/templates/pdf/_tokens.css` (included by `shared_pdf_base.html`), the chart palette via `backend/invoices/generated_chart_tokens.py`; the UI side via `frontend/src/styles/tokens.css` and `lib/chartTokens.ts` — all five outputs come from `scripts/generate-tokens.mjs`.

**Primitives (verbatim, the only allowed hex literals; core subset shown — the full committed set, including `--white`, `--brand-ink`, `--neutral-100`, the `--info/--success/--danger/--warning/--violet` badge fills and their text pairs, lives in `design/tokens.json` → `backend/templates/pdf/_tokens.css`):**

| Token | Hex | Role (PDF) | UI role |
|---|---|---|---|
| `--ink` | `#0f172a` | primary text | `--text-primary` (already matches UI `:root` `color` `index.css:3`) |
| `--ink-soft` | `#334155` | body in tables/cards | `--text-body` |
| `--muted` | `#64748b` | labels, eyebrows, meta | `--text-muted` |
| `--line` | `#e2e8f0` | borders, row seps | `--border-default` |
| `--line-subtle` | `#f1f5f9` | subtle seps | `--border-subtle` |
| `--surface` | `#f8faf7` | warm paper | `--app-bg` (replaces `#f8fafc` + sky radials) |
| `--brand` | `#143828` | forest mid-dark | `--interactive-hover` |
| `--brand-deep` | `#0d2b1d` | darkest forest | `--sidebar-bg`, dark table headers, primary button |
| `--brand-mid` | `#1f5c3a` | interactive green | `--interactive`, `--focus-ring`, selection accent |
| `--brand-pale` | `#e8f0ec` | pale fill | `--sidebar-active`, pill/selected-row bg |
| `--brand-glow` | `#d4e0d7` | stronger pale | category panels |
| `--gold` | `#bfa05a` | single decorative accent | decorative/display on dark only (see §5.2) |
| `--brand-accent` | `#9ec3ac` | on-dark secondary | secondary text on `--brand-deep` |
| `--brand-light` | `#d6ead9` | chart/hover | chart fills |
| `--brand-muted` | `#c8dccf` | chart/hover | chart fills |
| `--zebra` | `#f3f6f2` | zebra rows | zebra rows (docs keep; UI optional) |
| `--chart-surface` | `#fbfcfb` | chart card bg | chart card bg |
| `--subtotal-color` | `#24352c` | subtotal text | totals text |

**Document anatomy (not copied 1:1, but shared where it helps family resemblance):**

- `.document-header` flex + hairline + `brand-mid` 40mm underline (`shared_pdf_base.html:80-98`) — stays PDF-only; UI uses the simpler page-header/toolbar pattern from `2026-04-frontend-management-page-design.md:139-150`.
- `.page-meta` running header/footer (`shared_pdf_base.html:169-216`, `position: running(footer-meta)` + `@page @bottom-center {content: element(footer-meta)}`) — PDF-only.
- Invoice `amount-card` dark forest gradient (`invoice_pdf.html:91-113`) — stays as a **document** motif + at most one dark KPI card per screen view; never as the default button skin.
- Contract `section-heading` masked rule (`contract_pdf.html:20-43`) — PDF-only; UI section kickers are the eyebrow style without the spanning rule.

---

## 9. Phased rollout (every phase = independently mergeable PRs)

- **Phase 0 — Decide, instrument, picture it** (mockup gate waived; regenerated user-guide screenshots served as the acceptance artefacts — see §7.8)

- Merge this spec + ADR 0014 (D1–D9 incl. rejected alternatives).
- `design/tokens.json` + `scripts/generate-tokens.mjs` (schema-validated, deterministic, raw-literal chart outputs for TS + Python) + committed `frontend/src/styles/tokens.css` with semantics wired but **no visual sweep yet** (import added, values still resolve to current hexes where possible) — no user-visible change. The source policy lands here, before mockups: hex only in `primitives`; stylelint scope = frontend CSS/TSX; JSON + Python enforced by the generator `--check`.
- Freeze "before" screenshot set: `npm run screenshots` via `screenshots.config.ts` (de-CH, 1440×900) → `docs/user-guide/screenshots/` baseline copy.
- Code-only mockups `frontend/src/pages/design/Preview*.tsx` → PNG acceptance set (dashboard + invoice detail with embedded PDF + one dense CRUD). Review on PR; one accepted picture gates Phase 1.

### Phase 1 — Tokens + chrome + real preview

- Sweep `index.css` + `main.tsx` from semantics; drop sky radials; `body → var(--app-bg)`; `sidebar → var(--brand-deep)` (+ functional active state: `var(--brand-pale)` pill, 3px `var(--brand-mid)` bar).
- Buttons / focus rings / inputs / modals / toasts / `.badge-*` remapped; global `:focus-visible`.
- `PdfTemplatePreviewView` gains `?output=pdf` / `output:"pdf"` path; `AdminPdfTemplatesPage` shows object-URL `<iframe>` (debounced 700 ms, revision guard + `AbortController`, "re-rendering…" retention; HTML debug toggle = escaped source view, never executed). Preview render failures surface as a `400` banner in the editor; unexpected renderer failures return a generic `500` whose detail goes to the server log.
- `InvoiceDetailPage` restructured: operational chrome + embedded `pdf_url` via `PdfPreview` (+ generate-if-missing).
- Exit: no `#0ea5e9` sky family remains; template preview runs the same pipeline/template/tokens/PDF profile as issued documents and the invoice embed serves the stored artifact itself; `stylelint color-no-hex` is live in `pr-quality.yml` with a migration-aware allowlist (not-yet-swept files temporarily allowed, generated `tokens.css` allowed, JSON never in a CSS lint list).

### Phase 2 — Components for operations, not stationery

- Tables (plain + `DataTable`): sticky header, `tabular-nums`, right-aligned money/quantities, `36–40px` rows, hover/secondaries as §7.4.
- KPI/Stat cards (≤1 dark-accent per view), status pills (filled desaturated, never gold-on-white), forms/modals/toasts/empty states; `.badge-*` family migration.
- Delete `src/App.css`; cut over the five MUI `DatePicker` call sites to Mantine and remove `@mui/x-date-pickers` (§7.6).
- Uppercase eyebrows only as section kickers (CSS `text-transform`); form/filter labels stay `500` sentence-case.

### Phase 3 — Pages by operator frequency

Order: Dashboard → invoices list → participants → metering/imports → tariffs → settings → admin; login as quiet paper showcase. Follows `2026-04-frontend-management-page-design.md` shell `header → toolbar → filters → card/table → modals`. Every chart path (`DashboardPage`, `MeteringChartPage`, `TariffPriceHistoryChart`, `EnergyFlowChart`, `RawMeteringTable` grids) consumes generated chart tokens.

### Phase 4 — QA & rollout

- Regenerate `docs/user-guide/screenshots/*`; diff vs Phase 0.
- Contrast audit (axe or manual): AA+ everywhere — gold rule, `muted` on `brand-pale`/`zebra`, text on `brand-deep` all checked. Focus-visible pass, keyboard pass, locale check EN/DE/FR/IT (uppercase via CSS only; never in translation strings; long German compounds wrapping).
- Tighten the Phase 1 stylelint allowlist to the generated token outputs only (the sweep is done by now). Link this spec in `AGENTS.md`.
- Dead-CSS sweep of `index.css`: delete selectors no longer matched after Phases 1–3 (report before/after bytes + selector count in the PR).
- File the Phase 5 ADR: MUI Data Grid → TanStack Table and full MUI retirement — executed once Phase 4 acceptance confirms the visual language is stable (D7).

### Phase 5 — Retire MUI (simplification payoff; own ADR, gated on Phase 4 acceptance)

- Replace `DataGrid` on `ImportsPage` + `AdminInvoicesPage` with TanStack Table + the shared table CSS (§7.4). Parity checklist per page before deleting the `DataGrid` import: sorting, filtering, pagination, row selection, density, locale (`dataGridLocale.ts`), loading/empty states.
- Replace the remaining MUI widgets with Mantine equivalents: `Menu`/`MenuItem` (`ActionMenu`), `Drawer` (`AuditEventDrawer`), `Switch` (`MeteringPointFormModal`), `Tab`/`Tabs`/`Switch` (`AdminSystemSettingsPage`).
- Remove `@mui/material`, `@mui/x-data-grid`, `@emotion/react`, `@emotion/styled` from `package.json`; delete `lib/dataGridLocale.ts`.
- Exit: zero `@mui/*`/`@emotion/*` imports in `src/`; one date system (Mantine), one styling system (tokens + hand-rolled contracts); bundle measurably smaller (report before/after).

---

## 10. Change inventory (file-level)

**New:**

- `design/tokens.json` + `scripts/generate-tokens.mjs` + `design/tokens.test.mjs`
- `frontend/src/styles/tokens.css` (generated, committed)
- `frontend/src/styles/generatedTheme.ts` (generated Mantine theme, committed)
- `backend/invoices/generated_chart_tokens.py` (generated chart constants, committed)
- `frontend/src/components/DataTable.tsx` (TanStack-backed shared table, `.data-table` CSS contract)
- `@tanstack/react-table` dependency (Phase 5 only)
- `frontend/src/components/PdfPreview.tsx`
- (dropped — see §7.8)
- `backend/templates/pdf/_tokens.css` (generated primitives include)
- `docs/specs/2026-08-ui-redesign-pdf-style.md` (this spec) + `docs/adr/0014-*.md`
- stylelint config (`.stylelintrc.json` or `frontend/.stylelintrc.json`); the hex→semantic grep inventory lives in the spec PR's description, not in the repo

**Backend changed (minimal):**

- `invoices/views_templates.py` — `PdfTemplatePreviewView.post` adds `output` branch, calls `render_pdf()` for `application/pdf` response; no permission or audit change.
- `backend/invoices/pdf_charts.py` — palette constants imported from `generated_chart_tokens.py` (duplicated literals removed).
- `backend/templates/pdf/shared_pdf_base.html` — replace the literal `:root` block (lines 23-42, inside the file's single `<style>` partial) with `{% include "pdf/_tokens.css" %}` so `_tokens.css` becomes the hex source. The include belongs inside the `<style>` block (consumers already include the base, e.g. `invoice_pdf.html:11`; the base's lines 1-20 are an inert `{% comment %}` usage note). No change to `PdfTemplate` override resolution (DB HTML stays standalone, keeps working without the include).

**Frontend changed:**

- `frontend/src/main.tsx` — imports generated `styles/tokens.css` + `styles/generatedTheme.ts` (forest ramp replaces sky `#f0f9ff … #0c4a6e`; the entrypoint itself stays hand-written).
- `frontend/src/index.css` — full token sweep (§7.2): shell/sidebar/buttons/stat-card/page-stack/badge-*/inputs/modals/toasts/mobile-menu/impersonation-banner/login.
- `frontend/src/pages/ReportsPage.tsx` + `frontend/src/features/reports/YearDownloadCard.tsx` + `frontend/src/features/reports/ReportsEmptyState.tsx` — new `/reports` page (lazy route in `App.tsx`, `ProtectedRoute allowedRoles={['admin','zev_owner','participant']}`) with a shared page-level year selector, a `grid grid-2` card row, `YearDownloadCard` deduping the download-card pattern, and `ReportsEmptyState` for the ZEV guard; `DashboardPage` slim-down (download controls, mutations, `annualStatementYear` state, `dashboard.quickStart` i18n key removed; header eyebrow → selected ZEV scope line). `Layout.tsx` adds `nav.reports` + `ReportsIcon` between Invoices and Feasibility, visible to admin/zev_owner/participant via the exported `canSeeReports(role)` guard (matching the route's `allowedRoles` — participants reach their statement download through the nav, not only by URL); `frontend/src/i18n/locales/{de,en,fr,it}.ts` move the download strings under `pages.reports.*`. `AppFooter.tsx`, `LanguageSelector.tsx`, `StatCard.tsx`, `ActionMenu.tsx`, `ConfirmDialog.tsx`/`FormModal.tsx`/`EmailLogsModal.tsx`, `PeriodSelector.tsx`, `RawMeteringTable.tsx`, `EnergyFlowChart.tsx`, `frontend/src/lib/chartTokens.ts` + feature folders.
- `frontend/src/components/DateLocaleProvider.tsx` — drop the MUI `LocalizationProvider`/`AdapterDayjs` half; Mantine `DatesProvider` only (Phase 2).
- The five date-picker call sites (`ZevGeneralSettingsFields`, `AdminVatSettingsPage`, `TariffFormModal`, `MeteringAssignmentFormModal`, `TariffVersionModal`) — MUI `DatePicker` → Mantine `DatePickerInput` (Phase 2).
- Phase 5: `ImportsPage`/`AdminInvoicesPage` to TanStack Table; `ActionMenu`, `AuditEventDrawer`, `MeteringPointFormModal`, `AdminSystemSettingsPage` MUI widgets → Mantine; delete `lib/dataGridLocale.ts`.
- `package.json`: remove `@mui/x-date-pickers` (Phase 2); Phase 5 adds `@tanstack/react-table` and removes `@mui/material`, `@mui/x-data-grid`, `@emotion/react`, `@emotion/styled`.
- Pages: `DashboardPage` (slimmed: KPI → flow → exceptions → charts; no downloads; scope-line eyebrow), `ReportsPage` (`/reports`, `YearDownloadCard` dedup, role-branched downloads), `InvoicesPage`, `InvoiceDetailPage` (chrome+embed), `ParticipantsPage`, `TariffsPage`, `MeteringPointsPage`, `MeteringChartPage`, `ImportsPage`, `LoginPage`, admin pages, `ZevListPage`, `ZevSettingsPage`.
- `frontend/src/lib/api/invoices.ts` — `previewPdfTemplateBlob(content, templateType, signal?)` (always posts `output:"pdf"`).

**Deleted:** `frontend/src/App.css`; `@mui/x-date-pickers` (Phase 2); `@mui/material` + `@mui/x-data-grid` + `@emotion/*` (Phase 5).

**Regenerated:** `docs/user-guide/screenshots/*` (and `README.md` screenshot references for free).

---

## 11. Risks and guardrails

| Risk | Impact | Mitigation |
|---|---|---|
| 43 KB hand-rolled CSS with ≈211 hardcoded hexes | Medium | Phase 0 grep inventory `rg --pcre2 '#[0-9a-f]{3,8}\b'` + hex→semantic map; tokenise per-file; `stylelint color-no-hex` in CI from Phase 1 |
| `management-page-design` contract drift | Medium | Phase 2–3 PRs update `2026-04-frontend-management-page-design.md:100-112` (`.badge-*`/`.button*`/`.card`) in the same commit; CI checks import of `tokens.css` |
| Three styling systems drift again | Medium | D4/D7: tokens generated into all three; Mantine is a consumer; one Data Grid `sx` module; no new MUI; `@mui/x-date-pickers` removed in Phase 2 and all MUI retired in Phase 5 — the trajectory ends at one styling system |
| MUI → Mantine date-picker cutover regressions (locale text, value handling) | Low | Five call sites only; `DatesProvider` already localises Mantine; per-site visual + keyboard check in Phase 2 |
| Data Grid → TanStack Table feature parity (sorting/filter/pagination/selection/density) | Medium | Phase 5 gated on Phase 4 acceptance; per-page port with the parity checklist before the `DataGrid` import is deleted |
| WeasyPrint preview latency | Medium | Debounce + keep-last-render; "re-rendering…" state; render only on demand; error banner on `400`; source toggle shows the raw template markup (no server round-trip) |
| PDF/A-3b in object-URL `<iframe>` | Low | Native viewers handle PDF/A; verify Chrome/Firefox/Safari desktop in Phase 1 exit; fallback link "Open in new tab" |
| Gold/green contrast in dense tables | Medium | Gold = display-on-dark only (§5.2); tables use desaturated status pills; Phase 4 axe AA+ gate |
| Customised `PdfTemplate` DB overrides | Low | Untouched; overrides that inlined old hexes are flagged `is_stale` via existing `default_digest` (digest compares generated default) — by design |
| Long DE/FR/IT uppercase labels overflow | Low | `text-transform` in CSS only; wrap + check all 4 locales in Phase 4 |
| Scope creep into "luxury stationery" | Medium | §5.1 + §5.2 + §5.3 as review checklist on every PR; one accepted mockup per page |

---

## 12. Test plan

### Backend — `invoices/test_template_admin.py` / `invoices/test_pdf.py` delta

Existing suites stay green (contract: 48 tests in `test_contract_context.py`; template admin: 40 in `test_template_admin.py`, 15 of them added or rewritten by this spec's preview/fetch/PDF-download work; invoice: `InvoicePdfRenderingTests` etc.).

**`PdfTemplatePreviewTests`** ( `invoices/test_template_admin.py`) — 11 tests:

| Test | Asserts |
|---|---|
| `test_each_template_type_renders_its_own_sample_context` | each of invoice/contract/annual_statement → `200 {html}` with its own sample context |
| `test_unknown_template_type_is_rejected` | body `template_type: "nonsense"` → `400 {"error": "Unsupported template type."}` (PATCH save path keeps the invoice fallback) |
| `test_broken_template_returns_400_not_500` | broken Django syntax without template_type → `400 {error}` |
| `test_blank_content_is_rejected` | blank/whitespace content → `400` |
| `test_preview_pdf_output_returns_pdf_bytes` | `output:"pdf"` in body and `?output=pdf` in query → `200`, `Content-Type: application/pdf`, `Content-Disposition: inline`, body starts `%PDF-` |
| `test_preview_pdf_rejects_broken_template_with_400` | broken syntax → `400 {error}` for both `html` and `pdf` modes; nothing stored |
| `test_preview_rejects_oversized_content` | content above `MAX_PREVIEW_CHARS` (500 000) → `400` mentioning the preview cap |
| `test_preview_rejects_unknown_output` | `output:"docx"` → `400` |
| `test_preview_ignores_external_resource_references` | template with `file:///etc/passwd` and `http://…` `<img>` references still renders `200 application/pdf` — the restricted fetcher degrades them like missing resources |
| `test_preview_denials_are_not_audit_logged` | participant `POST` → `403` with no DENIED audit event (no `denial_audit` override — DENIED events exist only on the mutation views) |
| `test_accept_pdf_header_does_not_fail_content_negotiation` | `Accept: application/pdf` on the JSON path falls back to the default renderer instead of answering 406 |

**`PdfRenderFetchPolicyTests`** (same module) — pins the `render_pdf` protocol boundary at the fetcher itself: `file:`/`http:`/`https:`/`ftp:` URLs raise, `data:` URIs fetch. Non-admin denial on the preview is additionally covered by the `ALL_ENDPOINTS` permission loops at the top of the module.

**`InvoicePdfDownloadTests`** (same module, 5 tests) — authenticated `GET /invoices/{id}/pdf/` endpoint:

| Test | Asserts |
|---|---|
| `test_pdf_returns_200_pdf_for_owner` | ZEV owner → 200 `application/pdf`, streaming body starts `%PDF-` |
| `test_pdf_returns_200_for_own_participant` | participant assigned to that invoice → 200 |
| `test_pdf_returns_404_when_no_pdf_file` | invoice with no stored `pdf_file` → 404 |
| `test_pdf_returns_404_for_out_of_scope` | user not in the invoice's ZEV scope → 404 (not 403) |
| `test_pdf_returns_401_for_anonymous` | unauthenticated → 401 |

**Staleness after token move** — `test_get_flags_override_saved_against_an_older_default_as_stale` now covers the post-move default (digest over `shared_pdf_base.html` + `_tokens.css`), so a release that changes a token file flags stale overrides.

**Save-path cap** — `test_oversized_override_is_rejected_and_nothing_is_stored` pins that `PATCH` enforces the same `MAX_TEMPLATE_CHARS` cap as the preview (a stored override renders through the same WeasyPrint pipeline, so the "bound renderer work" invariant has one size limit in both places).

### Frontend

- `npm run test:unit` (if present) + `npm run build` green; `stylelint` step green ( `pr-quality.yml`).
- `scripts/generate-tokens.mjs` idempotence test `design/tokens.test.mjs`: write→read→generate→diff → `0`; brand-ramp monotonicity negative test: inverted/tied ramp in a temp tree → non-zero exit in both generate and `--check` modes.
- Playwright `npm run screenshots` (1440×900 de-CH) regenerated — 22/22 captures committed under `docs/user-guide/screenshots/`.
- Preview editor: revision guard ignores out-of-order responses; superseded requests are aborted (`AbortController`).
- Date-picker cutover matrix: each of the five converted pickers displays and submits the same plain civil-date format as before (no local-time shift, ADR 0007).

### Tooling — `pr-quality.yml`

| Job | Command | Gate |
|---|---|---|
| `lint:style` + color sweep | `npm run lint:style` (stylelint `color-no-hex` on `src/**/*.css`; only the generated `tokens.css` is allowlisted) and `node ../scripts/check-frontend-hex.mjs` (hex **and** `rgb()/rgba()/hsl()/hsla()` sweep across TSX/CSS/backend templates/Python; `@alpha` allowlist entries sanction neutral scrims only) | No new raw color literals in hand-written source |
| `lint:types` | `npm run build` | No TS regressions |
| `tokens` | `node scripts/generate-tokens.mjs --check` | No drift between `tokens.json` and generated outputs and no brand-ramp luminance inversion |

### Manual verification

- Preview each template type (invoice / contract / annual statement) in de/fr/it/en: rendered PDF paginates as expected (invoice 2–3pp, contract 3–7pp), running footer on every page, QR 106mm `@page` not duplicated (existing `_count_qr_slips` guard still holds), signature block never split.
- `InvoiceDetailPage` with and without existing `pdf_file`: embed shows shipped bytes, generate-if-missing reuses `generate-pdf/` and then embeds.
- Contrast: sample each page family with axe — gold on white absent, `muted` on `brand-pale` ≥4.5:1, text on `brand-deep` ≥7:1.
- Keyboard/focus-visible: tab through `Layout`, `PeriodSelector`, `AdminPdfTemplatesPage` tabs (roving tabindex + arrow keys), modal traps, header/Data Grid pickers show `2px` `--focus-ring`.
- All 4 locales: long DE compounds wrap without overflow in invoice lists / metering cards / tariff names.
- CSP and embed behaviour: object-URL iframes work with the app's CSP (`frame-src`/`object-src`) on Chrome, Firefox and Safari; the previous object URL is revoked only after the replacement frame loaded; download/open-in-new-tab fallback works.
- PDF accessibility (PDF/UA, tagged PDF, native-viewer a11y) is explicitly out of scope — axe covers the React app only; PDF/UA would be its own requirement.

### Acceptance criteria

- [x] Template preview uses the same rendering pipeline, template version, token output and PDF profile as issued documents (no HTML facsimile; parity, not byte-equality); invoice detail page embeds the stored artifact via authenticated blob fetch (contract and annual-statement embeds deferred — §§2,6.2).
- [x] No `#0ea5e9` sky-blue family remains and the sidebar is `--brand-deep`, not slate (`#0f172a` survives only as the `--ink`/`CHART_INK` token *value* — a different role); zero raw hex — and zero raw `rgb()/rgba()/hsl()/hsla()` outside the sanctioned neutral alpha scrims — in hand-written frontend source, backend templates, and `invoices` Python outside `design/tokens.json` and its five generated outputs (lint + color-sweep gates green; the sweep covers color functions and the backend surfaces too, with per-file `@alpha` allowlist entries for scrims/shadows). Hex literals inside `test_pdf.py` assert generated values and are exempt.
- [x] Token names identical across `tokens.json` and its five generated outputs (`tokens.css`, `generatedTheme.ts`, `chartTokens.ts`, `generated_chart_tokens.py`, `pdf/_tokens.css`) — a design change lands in one file and all five regenerate without hand edits.
- N/A: "clear, calm, scannable" review against Phase 0 code-only mockups — the mockups were dropped (§7.8); the regenerated user-guide screenshots served as the review artefacts instead.
- [x] Charts on screen (recharts) and in PDFs (SVG) share the same hexes from `charts` block — verified by token-idempotence test.
- [x] Screenshots regenerated (`docs/user-guide/screenshots/*`), contrast AA+ (gold rule satisfied, axe green), focus-visible everywhere, spec + ADR 0014 linked in `AGENTS.md`.
- [x] This spec's file names, token hexes, `@page`/`running()` mechanics, endpoint shapes and query keys verified against code (§5–§7).
- [x] No new UI library or styling dependency during the redesign (and MUI was retired entirely rather than added to).
- [x] Dependency reduction: zero `@mui/*`/`@emotion/*` packages remain (retired in one sweep, not phased); sole new runtime dependency is `@tanstack/react-table`. `index.css` did **not** shrink (43.6 KB → 50.1 KB): it absorbed the design-system rules formerly spread across hand-rolled page CSS; `App.css` (-184 lines) was deleted with it.

---

## 13. Rejected alternatives (see ADR 0014)

- Svelte rewrite — wrong problem (design quality orthogonal to framework); large-scale churn, and the same token work still has to be done afterwards.
- Typst compiler — severs HTML/CSS bridge that makes print↔web parity cheap; revisit only if free-form HTML overrides are dropped for a closed document system.
- Consolidate fully on Mantine — large-scale churn for a styling change.
- HTML facsimile of the invoice detail — two sources of truth that drift; superseded by embedding the real PDF (§6.2).

---

## 14. Implementation notes (Phases 0–5, this branch)

- **Phase 0** — `design/tokens.json`, `scripts/generate-tokens.mjs` (+ `--check`),
  `design/tokens.test.mjs`, five committed generated outputs. The generator holds
  zero hex literals: the 10-step Mantine ramp derives from primitives plus
  `charts.prodColors[1]`; `--brand-ink` was added for the darkest step. Chart
  tokens gained `positiveColor`/`negativeColor` during Phase 3, plus `divergingPositive` (validated blue half of the blue/red diverging pair) during review follow-up. The generator also asserts WCAG 2.1 relative-luminance monotonicity (strictly decreasing) across the 10-step ramp (`--brand-pale` → `--brand-ink`) in both generate and `--check` modes, failing on any `--brand-glow` ↔ `--brand-muted` inversion (CI gate via `pr-quality.yml` `--check`).
- **Phase 1** — full `index.css` token sweep (zero raw hex), sidebar/nav active
  pill + leading bar, flat `.button`, desaturated badges incl. invoice workflow
  variants, global `:focus-visible`. `preview-pdf-template` accepts body
  `output:"pdf"` or query `?output=pdf` — **not** the originally specced
  `?format=pdf`: DRF's `URL_FORMAT_OVERRIDE` content negotiation intercepts
  unknown `format` values with a 404 before the view dispatches (see §6.1).
  Gates live in CI: stylelint `color-no-hex`, hex sweep
  (`scripts/check-frontend-hex.mjs`), token check + idempotence test.
- **Phase 2** — `CivilDateInput` wraps Mantine's `DatePickerInput`; Mantine
  natively emits `YYYY-MM-DD` strings (`toDateString` via local dayjs), so the
  ADR 0007 contract passes through unchanged with no Date round-trip.
  `@mui/x-date-pickers` removed; `DateLocaleProvider` reduced to `DatesProvider`.
  Operational table contract (sticky header, 36px rows, hover, tabular numerals).
  `src/App.css` deleted.
- **Phase 3** — all chart paths consume `lib/chartTokens.ts` literals
  (Recharts/SVG cannot resolve `var()`); remaining inline-style hexes remapped to
  semantic vars; login register panel flattened to brand-pale paper. The
  hand-written frontend is hex-free, so the Phase 1 migration allowlist ships
  empty (Phase 4 tightening done early).
- **Phase 4 partial** — dead-CSS sweep applied (index.css 46,676 → 44,953 B in
  the sweep itself; follow-up phases grew it again, and the dead-selector
  cleanup after MUI retirement (`.factstrip`, the unused `pdf-frame` viewer-bar
  rules, duplicated `.page-stack`/`.data-table` blocks) brought it back down
  to ≈49 KB);
  dead selectors removed incl. unused nav-info/nav-zev-selector blocks,
  `bullet-list`, card-meta/badges leftovers, and the pre-redesign datepicker
  overrides whose hashed-class selectors matched nothing — selected-day styling
  now comes from the generated theme's `primaryColor`). Scripted WCAG AA ratio
  audit of the shipped semantic pairs passes; the one failure found
  (muted-on-brand-pale) was fixed by using `--ink-soft` on pale surfaces.
- **Screenshot regeneration** — `docs/user-guide/screenshots/*` re-captured
  against the redesigned UI (22/22 Playwright captures, de-CH, base viewport
  1440×900; `screenshots.config.ts` defaults to the full `chromium` channel
  so embedded PDFs render, and the 08b/14 captures assert the PDF viewer
  painted so a blank embed fails the run instead of being committed
  silently). Every
  capture goes through `screenshotFull` (`capture.spec.ts`): the viewport is
  grown to the content height instead of using `fullPage`, which captures
  beyond the viewport without re-resolving `100dvh` — the sticky sidebar
  would stop at 900 px while the main column continues — and in which
  Chromium's PDF plugin (viewport-only painting) leaves embedded viewers
  blank. Because the PDF embeds are 70–72 vh, the helper re-measures after
  resizing and solves the linear content-height model to its fixed point in
  one step; only the 04b assign modal keeps a plain viewport shot. The
  data-dependent captures pin the global ZEV selection to the seeded demo
  ZEV, because the app's fallback otherwise lands on an arbitrary empty
  tenant of this database. Bare-metal capture must set
  `VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000` (otherwise `/media` proxies
  to `backend:8000` and `08b-invoice-detail` shows `pdfError`);
  `capture.spec.ts` resets hover (`page.mouse.move(0,0)` + 250 ms) before
  every shot, and `08b` generates the invoice PDF via the API first
  (reseeds wipe stored artifacts). A full run makes ~28 token logins against
  the `auth_login` throttle (40/hour) — when rerunning within the hour,
  flush the throttle counters first (`docker compose exec redis redis-cli
  -n 1 FLUSHDB`; celery uses db 0). Screenshots ship unblurred: the demo
  seed carries fictional data, so the former PII blur CSS and its selector
  test were removed. **A11y pass completed** (see "Four-locale keyboard/a11y
  pass" below).

- **Phase 5** — MUI fully retired per ADR 0015: `ImportsPage` and
  `AdminInvoicesPage` moved to a shared TanStack-based `DataTable`
  (`@tanstack/react-table` v8), `ActionMenu` → Mantine `Menu`,
  `AuditEventDrawer` → Mantine `Drawer`, remaining `Switch`/`Tabs` → Mantine.
  Removed: `@mui/material`, `@mui/x-data-grid`, `@emotion/react`,
  `@emotion/styled`, `lib/dataGridLocale.ts`. The bundle's dedicated MUI
  vendor chunk is gone.

- **Follow-up fixes (post-Phase-5 review)** — the preview editor's debounced
  effect depended on its own output state (`rendering`/`previewUrl`), so every
  successful render re-triggered another fetch and the explicit Render button's
  request was always aborted; one shared `renderPreview(source)` path now owns
  revision/abort/object-URL lifecycle. `InvoiceDetailPage` PDF-generation
  failures surface a translated error instead of rejecting unhandled;
  `.text-error`/`.app-route-loading` were referenced but undefined since the
  `App.css` deletion and are now defined. The preview endpoint validates
  `template_type` (400 on unknown), returns a generic 500 body (detail via
  `logger.exception`), and its docstring no longer advertises the dead
  `?format=pdf` spelling. `render_pdf` restricts WeasyPrint fetching to
  `data:` URIs on all paths (§6.1). The token generator's hex-containment
  regex lost its stateful `g` flag, stale MUI chunk-split config was removed,
  and the pre-redesign chart colours in `annual_statement.py`/`pdf_charts.py`
  were remapped onto the shared chart palette (§4.3) — nothing is in
  production, so no frozen values remain. The legacy
  annual-statement/financial-summary templates followed in the same pass:
  both now include `pdf/_tokens.css` and reference `var(--…)` (dark
  `--brand-deep` table headers with white text, `--brand-mid` accents,
  ink/muted/line grey ladder, `--brand-pale` highlight washes), and the
  invoice/contract white fills became `var(--white)`; the hex sweep was
  extended to the backend surfaces so the state is enforced, not just
  reached. The per-ZEV email-template editor (`ZevEmailTemplateFields`) was
  aligned post-review too: its "Verfügbare Felder" list had drifted from the
  admin E-Mail-Vorlagen page (missing `{due_date}`, which the backend render
  context and model help text always supported) and still used pre-redesign
  table styling; it now lists all 7 variables and shares the token-styled
   field-table treatment of the admin template pages (admin-governance
   baseline spec §9.7 updated accordingly). It has since been consolidated
   further: the variable list is rendered by the shared `EmailFieldReference`
   component, styled via the dedicated `.email-field-reference` CSS class in
   `frontend/src/index.css` (monospace variable column with ellipsis, fixed
   table layout, 50% first column). The four-locale keyboard/a11y
   pass is complete (below).

- **Four-locale keyboard/a11y pass** — executed in two steps. Static WCAG
  audit computed from `design/tokens.json` found five failing pairs, all
  fixed token-side: period-selector active preset label (`--muted` on
  `--brand-pale` 4.10:1 → `--ink-soft` 8.9:1), admin pending-emails KPI and
  data-quality yellow label (gold on light 2.50/2.33:1 → `--warning-800`,
  matching the green/red sibling pattern), email-log pending pill (white on
  gold 2.50:1 → `warning-800` fill ~6.4:1), and the impersonation banner's
  gold border (2.33:1 < 3:1 non-text → `--warning-300`). A live axe-core
  sweep (WCAG 2.0/2.1 A+AA, 11 pages × EN/DE/FR/IT) then found two serious
  issues: the scrollable field-reference asides on both admin template
  editors were not keyboard-reachable (`scrollable-region-focusable`; now
  focusable and labelled via a new `admin.fieldReference` key in all four
  locales) and the sidebar GitHub footer failed contrast (`--muted` on
  `--brand-deep` 3.20:1 → `--brand-accent` 7.86:1; version span opacity
  0.65 → 0.8 = 5.59:1). Re-sweep reports zero violations; keyboard tab-
  through (sidebar, `PeriodSelector`, template tabs with roving tabindex +
  Arrow/Home/End, modal traps), DE compound wrapping, uppercase-via-CSS,
  and object-URL iframe behaviour verified manually across browsers.
  User-guide screenshots regenerated afterwards.

- **Template-preview auto-render gate removed** — the Phase-5 size gate
  (>20 000 characters → render button only) sat below the shipped invoice
  (31k) and contract (34k) defaults, so those two tabs never auto-rendered
  and landed on a stale or empty preview. Editor and preview are mutually
  exclusive views (typing never triggers a render), so the gate only decided
  whether the single render on preview entry fires; it now fires for every
  template size (debounced 700 ms), bounded server-side by the 500 000-
  character preview cap, with the explicit Render button kept for manual
  re-renders. The same pass fixed the browser preview 406ing on its own
  `Accept: application/pdf` header: `PdfTemplatePreviewView` now falls back
  to the default renderer instead of raising `NotAcceptable` (regression
  test `test_accept_pdf_header_does_not_fail_content_negotiation`).
