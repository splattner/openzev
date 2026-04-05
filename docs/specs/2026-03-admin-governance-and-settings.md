# Feature Spec: Admin governance and platform settings

- Spec ID: SPEC-2026-admin-governance
- Status: Approved
- Scope: Major
- Type: Feature
- Owners: Core maintainers
- Created: 2026-03-24
- Target Release: Ongoing baseline
- Related Issues: n/a (baseline)
- Related ADRs: 0003, 0007, 0008
- Impacted Areas: backend, frontend, docs

---

## 1. Problem and outcome

Global settings (date formats, VAT rates) and ZEV-level configuration (billing interval, invoice numbering, email templates, contract notes) drive how every invoice is formatted, taxed, numbered, emailed, and printed. These settings must be consistent, admin-controlled where global, and ZEV-owner-editable where per-community.

**Outcome:** Admins manage a global singleton for regional date formats, a VAT-rate validity table, user accounts, and invoice PDF HTML templates. ZEV owners manage their own community billing, invoicing, email-template, and contract-note settings. A platform-wide dashboard gives admins an at-a-glance view of system health.

---

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Global AppSettings singleton | Date format choices (short, long, datetime) |
| VAT rate table | Non-overlapping validity windows, `active_for_day()` lookup |
| Admin dashboard | ZEV, participant, invoice, and email statistics |
| User account management | Admin-only CRUD with linked-account safety |
| Invoice PDF template | Read/edit the server-side HTML template file |
| ZEV-level settings | Billing interval, invoice prefix/counter/language, banking, email templates, contract notes |
| Contract PDF generation | Multi-language participation agreement using ZEV config |

### Out of scope

- Multi-country tax engines with jurisdiction-specific filing
- External policy synchronisation systems
- Audit-log data model (see ADR 0008 — currently `updated_at` only)

---

## 3. Actors, permissions, and ZEV scope

| Actor | Global settings | VAT rates | Dashboard | PDF template | User accounts | ZEV-level settings |
|---|---|---|---|---|---|---|
| `admin` | Read + Write | Full CRUD | Read | Read + Write | Full CRUD | Read + Write (all ZEVs) |
| `zev_owner` | Read only | No access | No access | No access | No access | Read + Write (own ZEVs) |
| `participant` | Read only | No access | No access | No access | No access | No access |
| `guest` | Read only | No access | No access | No access | No access | No access |

"Read only" for AppSettings means GET `/api/v1/auth/app-settings/` is allowed for any authenticated user; the frontend `AppSettingsProvider` loads it at boot for date formatting everywhere.

All admin-only surfaces are wrapped in `<ProtectedRoute allowedRoles={['admin']}>` on the frontend. On the backend, VAT rate endpoints use the `IsAdmin` permission class directly, while `app_settings`, `dashboard`, and `pdf_template` use `IsAuthenticated` with a manual `request.user.is_admin` check in the view body.

---

## 4. Data model

### 4.1 AppSettings (global singleton)

**Model:** `accounts.models.AppSettings`

Singleton pattern with `pk=1` enforced by `save()` plus a `singleton_enforcer = BooleanField(default=True, unique=True, editable=False)`.

| Field | Type | Default | Choices |
|---|---|---|---|
| `date_format_short` | CharField(20) | `dd.MM.yyyy` | `dd.MM.yyyy`, `dd/MM/yyyy`, `MM/dd/yyyy`, `yyyy-MM-dd` |
| `date_format_long` | CharField(20) | `d MMMM yyyy` | `d MMMM yyyy`, `d. MMMM yyyy`, `MMMM d, yyyy`, `yyyy-MM-dd` |
| `date_time_format` | CharField(25) | `dd.MM.yyyy HH:mm` | `dd.MM.yyyy HH:mm`, `dd/MM/yyyy HH:mm`, `MM/dd/yyyy HH:mm`, `yyyy-MM-dd HH:mm` |
| `updated_at` | DateTimeField | auto_now | — |

**Key methods:**
- `save()` — Forces `pk=1` and `singleton_enforcer=True` before calling `super().save()`.
- `load()` (classmethod) — `get_or_create(pk=1, defaults={…})`, returns the singleton.

**Serializer:** `AppSettingsSerializer` — exposes `date_format_short`, `date_format_long`, `date_time_format`, `updated_at` (read-only).

### 4.2 VatRate

**Model:** `accounts.models.VatRate`

| Field | Type | Constraints |
|---|---|---|
| `rate` | DecimalField(5, 4) | `MinValueValidator(0)`, `MaxValueValidator(1)`. Stored as fraction (e.g. `0.0810` = 8.10 %). |
| `valid_from` | DateField | Required. |
| `valid_to` | DateField | Nullable. `None` = open-ended / currently active. |
| `created_at` | DateTimeField | auto_now_add |
| `updated_at` | DateTimeField | auto_now |

**Ordering:** `["-valid_from", "-created_at"]`

**Validation (`clean()`):**
1. If `valid_to` is set, `valid_to >= valid_from`, else `ValidationError({"valid_to": "…"})`.
2. No overlapping ranges: `VatRate.objects.exclude(pk=self.pk).filter(valid_from__lte=candidate_end).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=self.valid_from))` must be empty.
3. `save()` calls `full_clean()` to enforce validation on every create/update.

**Key methods:**
- `active_for_day(day)` (classmethod) — Returns the first `VatRate` where `valid_from <= day` and (`valid_to IS NULL` or `valid_to >= day`), ordered by `-valid_from`, `-created_at`. Returns `None` if no match.

**Serializers:**
- `VatRateSerializer` — fields: `id`, `rate`, `valid_from`, `valid_to`, `created_at`, `updated_at` (id/created_at/updated_at read-only).
- `VatRateInputSerializer` — fields: `rate`, `valid_from`, `valid_to`.

### 4.3 Zev governance fields

**Model:** `zev.models.Zev` (selected fields relevant to admin/governance)

| Field | Type | Default | Notes |
|---|---|---|---|
| `billing_interval` | CharField(20) | `monthly` | Choices: `monthly`, `quarterly`, `semi_annual`, `annual` (from `BillingInterval` TextChoices) |
| `invoice_prefix` | CharField(10) | `INV` | Used in `next_invoice_number()` |
| `invoice_counter` | PositiveIntegerField | `1` | Auto-incremented atomically via `F()` expression |
| `invoice_language` | CharField(2) | `de` | Choices: `de`, `fr`, `it`, `en` (from `InvoiceLanguage` TextChoices). Used for PDF + contract translation lookups. |
| `bank_iban` | CharField(34) | blank | For QR-Rechnung generation |
| `bank_name` | CharField(200) | blank | |
| `vat_number` | CharField(50) | blank | If non-empty, VAT is applied to invoices |
| `email_subject_template` | CharField(500) | `""` (blank) | Python `.format_map()` template. Falls back to `DEFAULT_EMAIL_SUBJECT_TEMPLATE` if blank. |
| `email_body_template` | TextField | `""` (blank) | Python `.format_map()` template. Falls back to `DEFAULT_EMAIL_BODY_TEMPLATE` if blank. |
| `local_tariff_notes` | TextField | blank | Free-text shown on contract PDF |
| `additional_contract_notes` | TextField | blank | Additional agreements on contract PDF |
| `notes` | TextField | blank | General notes |

**Module-level defaults (`zev.models`):**
```python
DEFAULT_EMAIL_SUBJECT_TEMPLATE = "Invoice {invoice_number} – {zev_name}"
DEFAULT_EMAIL_BODY_TEMPLATE = (
    "Dear {participant_name},\n\n"
    "Please find your energy invoice for the period "
    "{period_start} to {period_end} attached.\n\n"
    "Total: CHF {total_chf}\n\n"
    "Kind regards,\n{zev_name}"
)
```

**Invoice numbering:**
- `next_invoice_number()` generates `"{prefix}-{counter:05d}"` (e.g. `INV-00001`).
- Atomically increments `invoice_counter` using `Zev.objects.filter(pk=self.pk).update(invoice_counter=F("invoice_counter") + 1)`.
- Calls `self.refresh_from_db()` after increment.

**Serializer:** `ZevSerializer` — `fields = "__all__"`, read-only: `id`, `created_at`, `updated_at`. `owner` is optional and defaults to `request.user`. Owner changes auto-promote/demote role (ZEV_OWNER ↔ PARTICIPANT).

---

## 5. API contracts

### 5.1 AppSettings

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/auth/app-settings/` | GET | `IsAuthenticated` | Returns current singleton via `AppSettings.load()` |
| `/api/v1/auth/app-settings/` | PATCH | `IsAdmin` | Partial update of date format fields. Returns updated singleton. |

**View:** `accounts.views.app_settings` — function-based view decorated with `@api_view(["GET", "PATCH"])` and `@permission_classes([IsAuthenticated])`. Admin check for PATCH: `if not request.user.is_admin: raise PermissionDenied(…)` — produces a DRF `{"detail": "…"}` 403 response.

### 5.2 VAT Rates

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/auth/vat-rates/` | GET | `IsAdmin` | List all rates ordered by `-valid_from`, `-created_at`. Paginated (`PaginatedResponse<VatRate>`). |
| `/api/v1/auth/vat-rates/` | POST | `IsAdmin` | Create rate. `perform_create` wraps Django `ValidationError` → DRF `ValidationError`. Returns 201. |
| `/api/v1/auth/vat-rates/{id}/` | GET | `IsAdmin` | Single rate detail. |
| `/api/v1/auth/vat-rates/{id}/` | PATCH | `IsAdmin` | Partial update. Wraps validation errors. Returns 200. |
| `/api/v1/auth/vat-rates/{id}/` | DELETE | `IsAdmin` | Delete rate. Returns 204. |

**Views:**
- `VatRateListCreateView(ListCreateAPIView)` — queryset: `VatRate.objects.all().order_by("-valid_from", "-created_at")`, serializer: `VatRateSerializer`, permission: `[IsAdmin]`.
- `VatRateDetailView(RetrieveUpdateDestroyAPIView)` — same queryset/permission, wraps `full_clean()` errors on update.

### 5.3 Admin Dashboard

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/invoices/invoices/dashboard/` | GET | `IsAuthenticated` + `is_admin` check | Aggregated platform statistics |

**Response shape (`DashboardStats`):**
```json
{
  "zevs": { "total": int },
  "participants": { "total": int },
  "invoices": {
    "draft": int, "approved": int, "sent": int, "paid": int, "cancelled": int,
    "total_revenue": float   // sum of total_chf for SENT + PAID invoices
  },
  "emails": { "total": int, "sent": int, "failed": int, "pending": int },
  "recent_invoices": [
    { "invoice_number": str, "participant_name": str, "zev_name": str,
      "total_chf": float, "status": str, "created_at": str }
  ]  // 10 most recent, ordered by -created_at
}
```

**Implementation:** Custom `@action(detail=False, methods=["get"])` on `InvoiceViewSet`. Aggregates using Django ORM `Count` and `Sum` with `Q` filters. Invoice stats exclude cancelled invoices from count. Revenue = `Sum('total_chf', filter=Q(status__in=[SENT, PAID]))`.

### 5.4 Invoice PDF Template

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/invoices/invoices/pdf-template/` | GET | `IsAuthenticated` + `is_admin` check | Returns `{ template_name, content }` — reads the HTML file from disk |
| `/api/v1/invoices/invoices/pdf-template/` | PATCH | `IsAuthenticated` + `is_admin` check | Writes new content to the template file on disk. Returns `{ template_name, content, detail }` |

**Implementation:** Custom `@action` on `InvoiceViewSet`. Template path is resolved via `_get_invoice_template_path()` which points to the Django template file at `TEMPLATE_NAME = "invoices/invoice_pdf.html"`. Content is read/written as UTF-8 text directly from/to the filesystem.

**Response type (`PdfTemplateResponse`):**
```typescript
interface PdfTemplateResponse {
    template_name: string   // e.g. "invoices/invoice_pdf.html"
    content: string         // raw HTML
    detail?: string         // success message on PATCH
}
```

### 5.5 ZEV Settings (per-community)

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/zev/zevs/{id}/` | PATCH | `IsAdmin` or `IsZevOwner` | Partial update of any Zev field including billing, email templates, contract notes |

Handled by `ZevViewSet` with `ZevSerializer`. All Zev fields (billing_interval, invoice_prefix, invoice_language, bank_iban, bank_name, vat_number, email_subject_template, email_body_template, local_tariff_notes, additional_contract_notes, notes) are writable.

---

## 6. Email template rendering

**Celery task:** `invoices.tasks.send_invoice_email_task` (shared_task, `bind=True`, `max_retries=3`).

Template variable resolution:
1. Loads `AppSettings` for date formatting.
2. Formats `period_start` and `period_end` using `_format_date_value(date, app_settings.date_format_short)`.
3. Builds `template_ctx` dict with 6 variables:

| Variable | Source |
|---|---|
| `{invoice_number}` | `invoice.invoice_number` |
| `{zev_name}` | `invoice.zev.name` |
| `{participant_name}` | `invoice.participant.full_name` |
| `{period_start}` | Formatted date |
| `{period_end}` | Formatted date |
| `{total_chf}` | `invoice.total_chf` |

4. Resolves templates: `zev.email_subject_template or DEFAULT_EMAIL_SUBJECT_TEMPLATE`, same for body.
5. Calls `.format_map(template_ctx)`. On `KeyError`/`ValueError`, falls back to defaults and logs a warning.
6. Attaches invoice PDF, sends via `EmailMessage`, logs to `EmailLog`.

---

## 7. Contract PDF generation

**Module:** `invoices.contract_pdf`

Uses `CONTRACT_TEMPLATE_NAME = "contracts/participant_contract_pdf.html"` rendered with WeasyPrint.

**Multi-language support:** `CONTRACT_TRANSLATIONS` dict with keys `de`, `fr`, `it`, `en`. Language is determined by `zev.invoice_language or "de"`.

**Context built by `_build_contract_context(participant)`:**

| Key | Source |
|---|---|
| `participant` | The participant record |
| `owner_participant` | ZEV owner's participant profile |
| `zev` | The ZEV record |
| `consumption_mps` | Assigned consumption/bidirectional metering points |
| `production_mps` | Assigned production metering points |
| `local_tariff_rows` | Active local energy tariffs (rate + calculation display) |
| `billing_interval_display` | Translated billing interval string |
| `contract_date` | Today formatted as `dd.mm.yyyy` |
| `tr` | Translation dict for chosen language |
| `lang` | Language code |
| `local_tariff_notes` | `zev.local_tariff_notes or ""` |
| `additional_contract_notes` | `zev.additional_contract_notes or ""` |

**Local tariff display:** `_build_local_tariff_display(zev, lang, tr)` iterates active local-energy tariffs, handles both fixed-price and percentage-of-energy billing modes. For percentage mode, it computes effective Rp/kWh by multiplying the percentage by the sum of active grid-tariff HT/flat prices.

---

## 8. Invoice PDF generation

**Module:** `invoices.pdf`

Template: `TEMPLATE_NAME = "invoices/invoice_pdf.html"` — editable by admins via the PDF template API.

**Context built by `_build_template_context(invoice)`:**
- Loads `AppSettings.load()` for date formatting
- Language: `invoice.zev.invoice_language or "de"`, uses `INVOICE_TRANSLATIONS[lang]`
- Dates formatted as `_format_date_value(date, app_settings.date_format_short)` for invoice_date, period_start, period_end, due_date
- Includes: invoice, items (grouped by category), zev, participant, owner_participant, QR-Rechnung SVG, energy chart SVG, hourly profile chart SVG, savings data

`generate_pdf(invoice)` renders HTML via `render_to_string()` and converts to PDF with WeasyPrint.
`save_invoice_pdf(invoice)` generates and attaches as `invoice_{number}.pdf`.

---

## 9. Frontend

### 9.1 AppSettings provider

**File:** `frontend/src/lib/appSettings.tsx`

- `AppSettingsContext` with `useAppSettings()` hook providing `{ settings, isLoading }`.
- `DEFAULT_APP_SETTINGS`: `date_format_short: 'dd.MM.yyyy'`, `date_format_long: 'd MMMM yyyy'`, `date_time_format: 'dd.MM.yyyy HH:mm'`.
- `SHORT_DATE_FORMAT_OPTIONS`, `LONG_DATE_FORMAT_OPTIONS`, `DATE_TIME_FORMAT_OPTIONS` — arrays of `{ value, label }` for dropdowns.
- `formatDateByPattern(value, pattern)` — Pure function that parses ISO date strings and formats using the chosen pattern. Uses `Intl.DateTimeFormat` for month names.
- `formatShortDate(value, settings)` — Convenience wrapper.
- `formatDateTime(value, settings)` — Formats ISO datetime strings.

### 9.2 Admin routes

All admin routes are nested under `/admin/*` and wrapped with `<ProtectedRoute allowedRoles={['admin']}>`:

| Route | Page component | Purpose |
|---|---|---|
| `/admin` | `AdminDashboardPage` | Platform statistics dashboard |
| `/admin/system-settings` | `AdminSystemSettingsPage` | Tabbed system settings for date formats, feature flags, and OAuth providers |
| `/admin/settings/vat` | `AdminVatSettingsPage` | VAT rate CRUD |
| `/admin/pdf-templates` | `AdminPdfTemplatesPage` | Invoice HTML template editor |
| `/admin/accounts` | `AdminAccountsPage` | User account management |
| `/admin/zevs` | `ZevListPage` | ZEV list management |

Legacy routes `/admin/settings/regional`, `/admin/features`, and `/admin/oauth`
remain available as redirects into the corresponding tab of
`/admin/system-settings`.

### 9.3 AdminDashboardPage

**File:** `frontend/src/pages/AdminDashboardPage.tsx`

- Query: `useQuery({ queryKey: ['dashboard'], queryFn: fetchDashboardStats, refetchInterval: 30000 })` — auto-refreshes every 30 seconds.
- Displays 4 key metric cards: total ZEVs, total participants, total revenue (CHF), pending emails (with failed count highlight).
- Invoice status breakdown: colour-coded grid of draft/approved/sent/paid/cancelled counts.
- Email statistics: total/sent/pending/failed with colour-coded cards.

### 9.4 AdminSystemSettingsPage

**File:** `frontend/src/pages/AdminSystemSettingsPage.tsx`

- Canonical route: `/admin/system-settings`
- Uses query-param tabs: `regional`, `features`, `oauth`
- Renders one page shell with a tab bar and per-tab content.
- **Regional tab:**
    - Loads current settings from `useAppSettings()`.
    - Form with 3 dropdowns: short date format, long date format, date & time format.
    - Live preview section showing formatted output for a sample date (`2026-03-18`) and datetime (`2026-03-18T14:35:00Z`).
    - Saves via `updateAppSettings` mutation. On success, updates the query cache directly: `queryClient.setQueryData(['app-settings'], data)`.
- **Functions tab:**
    - Uses `fetchFeatureFlags` with query key `['feature-flags']`.
    - Displays the registered feature flags in a table with toggle switches.
    - Toggling uses `updateFeatureFlag` and invalidates `['feature-flags']` after success.
- **OAuth tab:**
    - Uses `fetchOAuthProviderConfigs` with query key `['oauth-provider-configs']`.
    - Displays configured providers in a table with enabled badges and compact Edit/Delete actions.
    - Provider create/edit uses a shared modal form; delete uses `ConfirmDialog`.

Legacy routes `/admin/settings/regional`, `/admin/features`, and `/admin/oauth`
redirect to the matching tab on this page.

### 9.5 AdminVatSettingsPage

**File:** `frontend/src/pages/AdminVatSettingsPage.tsx`

- Query: `useQuery({ queryKey: ['vat-rates'], queryFn: fetchVatRates })`.
- **Create/Edit form:** 3 fields (rate %, valid_from date, valid_to date optional). Default rate: `8.1`. The frontend converts percentage to fraction before sending (`(percentage / 100).toFixed(4)`).
- **Rate table:** displays rate as percentage (`(rate × 100).toFixed(2)%`), valid_from (formatted), valid_to (formatted or "Open"), with Edit/Delete buttons.
- **Delete:** Uses `ConfirmDialog` component for destructive confirmation.
- **Validation feedback:** API errors (overlap, invalid range) displayed via toast.

### 9.6 AdminPdfTemplatesPage

**File:** `frontend/src/pages/AdminPdfTemplatesPage.tsx`

- Query: `useQuery({ queryKey: ['admin-pdf-template'], queryFn: fetchInvoicePdfTemplate })`.
- Displays template name (e.g. `invoices/invoice_pdf.html`) and a large `<textarea>` (24 rows, monospace) for editing the raw HTML.
- Save mutation sends the content string to `updateInvoicePdfTemplate(content)`.
- Success toast displays the `detail` message from the response.

### 9.7 ZevSettingsPage (per-community)

**File:** `frontend/src/pages/ZevSettingsPage.tsx`

Accessible to `admin` and `zev_owner` at route `/zev-settings`. Uses the globally selected ZEV from `useManagedZev()`.

Two form sections sharing the same submit mutation (`updateZev`):

**Section 1 — General Settings** (via `ZevGeneralSettingsFields` component):
- Name, start date (DatePicker with app-settings format), ZEV type (ZEV/vZEV), billing interval, invoice language
- Grid connection: grid operator, grid connection point
- Payment details: invoice prefix, VAT number, bank name, bank IBAN
- Notes, local tariff notes (contract PDF), additional contract notes (contract PDF)

**Section 2 — Email Template** (via `ZevEmailTemplateFields` component):
- Subject line input with placeholder showing system default
- Body textarea (10 rows) with placeholder showing system default
- Reset buttons to clear custom templates (reverts to system default)
- Expandable `<details>` section listing all 6 available template variables with descriptions

### 9.8 TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
type ShortDateFormat = 'dd.MM.yyyy' | 'dd/MM/yyyy' | 'MM/dd/yyyy' | 'yyyy-MM-dd'
type LongDateFormat = 'd MMMM yyyy' | 'd. MMMM yyyy' | 'MMMM d, yyyy' | 'yyyy-MM-dd'
type DateTimeFormat = 'dd.MM.yyyy HH:mm' | 'dd/MM/yyyy HH:mm' | 'MM/dd/yyyy HH:mm' | 'yyyy-MM-dd HH:mm'

interface AppSettings {
    date_format_short: ShortDateFormat
    date_format_long: LongDateFormat
    date_time_format: DateTimeFormat
    updated_at: string
}

interface AppSettingsInput {
    date_format_short?: ShortDateFormat
    date_format_long?: LongDateFormat
    date_time_format?: DateTimeFormat
}

interface VatRate {
    id: number
    rate: string        // decimal string e.g. "0.0810"
    valid_from: string
    valid_to?: string | null
    created_at: string
    updated_at: string
}

interface VatRateInput {
    rate: string
    valid_from: string
    valid_to?: string | null
}

interface DashboardStats {
    zevs: { total: number }
    participants: { total: number }
    invoices: {
        draft: number; approved: number; sent: number; paid: number; cancelled: number
        total_revenue: number
    }
    emails: { total: number; sent: number; failed: number; pending: number }
    recent_invoices: Array<{
        invoice_number: string; participant_name: string; zev_name: string
        total_chf: number; status: string; created_at: string
    }>
}

interface PdfTemplateResponse {
    template_name: string
    content: string
    detail?: string
}
```

### 9.9 API client functions

**File:** `frontend/src/lib/api.ts`

| Function | Method | Endpoint |
|---|---|---|
| `fetchAppSettings()` | GET | `/auth/app-settings/` |
| `updateAppSettings(payload)` | PATCH | `/auth/app-settings/` |
| `fetchVatRates()` | GET | `/auth/vat-rates/` |
| `createVatRate(payload)` | POST | `/auth/vat-rates/` |
| `updateVatRate(id, payload)` | PATCH | `/auth/vat-rates/{id}/` |
| `deleteVatRate(id)` | DELETE | `/auth/vat-rates/{id}/` |
| `fetchDashboardStats()` | GET | `/invoices/invoices/dashboard/` |
| `fetchInvoicePdfTemplate()` | GET | `/invoices/invoices/pdf-template/` |
| `updateInvoicePdfTemplate(content)` | PATCH | `/invoices/invoices/pdf-template/` |

---

## 10. Django Admin

**File:** `backend/accounts/admin.py`

| Admin class | Model | list_display |
|---|---|---|
| `CustomUserAdmin` | `User` | `username`, `email`, `first_name`, `last_name`, `role`, `is_active` |
| `AppSettingsAdmin` | `AppSettings` | `date_format_short`, `date_format_long`, `date_time_format`, `updated_at` |
| `VatRateAdmin` | `VatRate` | `rate`, `valid_from`, `valid_to`, `updated_at` (ordering: `-valid_from`, `-created_at`) |

`CustomUserAdmin` extends Django's `UserAdmin` with extra fieldsets for `role` and `must_change_password`.

---

## 11. Cross-cutting: date formatting in generated documents

Both invoice PDFs and invoice emails use `AppSettings.load()` to resolve the active `date_format_short` at render time.

- **Invoice PDF:** `_format_date_value(date, app_settings.date_format_short)` in `invoices.pdf._build_template_context` for `invoice_date`, `period_start`, `period_end`, `due_date`.
- **Invoice email:** Same `_format_date_value` call in `invoices.tasks.send_invoice_email_task` for `period_start` and `period_end` template variables.
- **Frontend:** All date rendering uses `formatDateByPattern()` / `formatShortDate()` / `formatDateTime()` from `appSettings.tsx`, which reads from the React context backed by the GET endpoint.

Changing date formats does NOT retroactively modify already-generated PDF files or previously sent emails — it only affects future rendering.

---

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Wrong VAT rate selected for invoice period | High | Non-overlapping validation in `clean()`. `active_for_day()` returns deterministic result. Test coverage for boundary dates. |
| Unauthorized settings changes | High | `IsAdmin` permission on all settings endpoints. `ProtectedRoute` on frontend. View-level `is_admin` checks on dashboard/PDF template actions. |
| Template regressions in generated PDFs | Medium | Admin can edit and preview HTML template. Template is a Django template file readable in plain text. |
| Email template rendering failure | Medium | `try/except` in task falls back to `DEFAULT_EMAIL_SUBJECT/BODY_TEMPLATE` and logs warning. Does not block sending. |
| VAT overlap allowing double taxation | High | `clean()` checks all existing ranges. `full_clean()` called in `save()`. API wraps validation errors for clear feedback. |

---

## 13. Test plan

### 13.1 Backend — `accounts/tests.py`

**`AppSettingsTests`** (3 tests):
| Test | Asserts |
|---|---|
| `test_authenticated_user_can_read_settings` | ZEV owner can GET `/auth/app-settings/` → 200, returns default format values |
| `test_admin_can_update_settings` | Admin PATCH all 3 format fields → 200, `AppSettings.load()` reflects new values |
| `test_non_admin_cannot_update_settings` | ZEV owner PATCH → 403 |

**`VatRateSettingsTests`** (4 tests):
| Test | Asserts |
|---|---|
| `test_admin_can_crud_vat_rates` | POST → 201, GET list → 1 result, PATCH rate → 200 with updated value, DELETE → 204 + not exists |
| `test_non_admin_cannot_manage_vat_rates` | ZEV owner GET → 403, POST → 403 |
| `test_vat_rate_ranges_cannot_overlap` | Pre-existing 2024–2025 rate. POST overlapping 2025-12–2026-12 → 400, error contains "overlap" |
| `test_vat_rate_valid_to_must_be_after_valid_from` | POST with valid_to < valid_from → 400, error contains "valid_to" |

**`RbacEndpointMatrixTests`** (6 tests):
Tests cover dashboard access (`test_invoice_dashboard_is_admin_only`) confirming admin→200, owner/participant/guest→403. Plus list/create/update/delete/unauthenticated endpoint matrices that include settings-adjacent endpoints.

### 13.2 Frontend

- AdminSystemSettingsPage: tab selector switches between regional settings, feature flags, and OAuth providers. Regional format selector renders all 4 options per format type, preview updates live, and save mutation calls `updateAppSettings`.
- AdminVatSettingsPage: form validates percentage 0–100, converts to fraction, create/edit/delete flows work. Overlap errors display as toast.
- AdminPdfTemplatesPage: textarea loads server content, save sends updated content.
- AdminDashboardPage: stats display, auto-refresh at 30s interval.
- ZevSettingsPage: general settings + email template sections both submit via `updateZev`. Reset buttons clear custom templates. Template variable reference is visible.

### 13.3 Acceptance criteria

- [ ] Platform admin can view and edit regional date formats; changes take effect system-wide for new renderings
- [ ] Platform admin can create, edit, and delete VAT rates with non-overlapping validity windows
- [ ] VAT rate overlap and invalid date range produce clear error messages
- [ ] Non-admin users cannot access VAT management, dashboard, PDF template, or account management
- [ ] Admin dashboard shows ZEV count, participant count, invoice status breakdown, email stats, and recent invoices with 30-second auto-refresh
- [ ] Admin can view and edit the invoice PDF HTML template through the browser
- [ ] ZEV owner can configure billing interval, invoice prefix, language, banking, email templates, and contract notes for their ZEV
- [ ] Email templates fall back to system defaults when left blank; rendering errors fall back gracefully
- [ ] Contract PDFs render in the ZEV's configured language (de/fr/it/en) and include local tariff notes and additional contract notes
- [ ] Invoice PDFs use `AppSettings.date_format_short` for all formatted dates
- [ ] Changing settings does not retroactively modify already-generated PDFs or sent emails

