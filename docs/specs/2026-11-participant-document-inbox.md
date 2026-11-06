# Feature Spec: Participant document inbox

- Spec ID: SPEC-2026-11-participant-document-inbox
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-11-05
- Target Release: next minor (phases 1–3), the release after (phase 6)
- Related Issues: [#862](https://github.com/splattner/openzev/issues/862); see also #761 (parties vs. accounts, shipped), #861 (draft invoices, shipped), #793 (anonymisation, open), #989 (notification center, shipped)
- Related ADRs: [ADR 0045](../adr/0045-delivered-documents-are-immutable-and-addressed-to-the-participant.md), [ADR 0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md), [ADR 0027](../adr/0027-per-zev-access-grants.md)
- Impacted Areas: backend | frontend | async jobs | docs

### Increments

| # | Delivered | PRs |
|---|---|---|
| 0 | This spec and ADR 0045 | — |
| 1 | `inbox` app: model, `deliver()` service, scoping, read and outbox API, backups (incl. per-ZEV restore), ZEV purge, audit | — |
| 1b | Transfer archive format 11 (`delivered_documents`) | — |
| 2 | Producers: invoice sent / superseded, explicit contract delivery, backfill command | — |
| 3 | Operator documents (upload, withdraw), issued annual statement / financial summary / tariff overview | — |
| 4 | Frontend: participant *Documents* page, manager outbox, upload and issue dialogs | — |
| 5 | Links and notifications: public invoice link and invoice email resolve to the inbox entry, `document.delivered` | — |
| 6 | Cut-over (follow-up release): participants lose the live invoice and report endpoints | — |

Each increment is its own PR and can ship alone. Phases 1–5 add; only phase 6 removes anything.

---

## 1. Problem and outcome

A participant reaches their documents through four unrelated paths, each with its own access rule:

- invoices through the live, ZEV-scoped `InvoiceViewSet` (sent-only since #861, kept after the link ends since #761, through `participant_visible` and `participant_access_survives_end` in `ZevScopedQuerySetMixin`);
- the annual statement, financial summary and tariff overview, rendered on demand from current data (`AnnualStatementView`, `FinancialSummaryView`, `TariffOverviewView`);
- the participation contract, stored as a fixed PDF in `ContractIssue`;
- the login-free invoice link (`InvoiceAccessToken`, the QR on the invoice).

Two consequences:

1. **There is nowhere for a document the operator wants to hand over**: the ZEV rules, a letter announcing a tariff change, minutes of a landowners' meeting.
2. **What a participant downloads later is not guaranteed to be what they received.** `Invoice.pdf_file` is cleared on approval and re-rendered by `save_invoice_pdf`, which the `generate-pdf` action runs at any status; the statement and summary re-render from current data on every download.

The access rules also differ by endpoint, so every new participant-visible resource needs its own exception in the scoping mixin.

**Outcome:** a per-participant **document inbox**: a list of documents that were actually delivered, each held as a fixed file. Two rules replace the per-endpoint exceptions:

- **Live data** (metering, dashboard, current tariffs) follows the participant link and ends at `valid_to`.
- **The inbox** holds what was delivered. Whoever is linked to that participant row can read it, with no end date, even after the ZEV is disabled.

## 2. Scope

### In scope

| Area | Details |
|---|---|
| Model | `inbox.DeliveredDocument`, one row per participant and delivered document |
| Service | `inbox.services.deliver()`, `supersede()`, `withdraw()`: the only writers |
| API | participant list / detail / download; manager outbox (same endpoints, wider scope); operator upload and withdraw; statement, summary and tariff-overview issue actions |
| Producers | invoice sent (`mark_invoice_sent`, `record_email_delivery`); invoice cancelled / replaced; explicit contract delivery |
| Public link | the login-free invoice page and its PDF serve the delivered snapshot |
| Notifications | `invoice.sent` links to the inbox entry; new `document.delivered` for every other kind |
| Backfill | idempotent command that creates entries for invoices already sent |
| Backup, transfer | the model and its files are covered by both archives |
| Audit | delivery, supersession and withdrawal events |
| Frontend | participant *Documents* page, manager outbox, operator upload, issue dialogs |
| Cut-over | remove participant access to the live invoice and report endpoints (phase 6) |
| Docs | user guide, baseline specs |

### Out of scope

- Two-way messaging or replies from participants.
- Documents addressed to accounts rather than participants (platform notices from an admin).
- **Read receipts.** Decided: not built. `delivered_at` is the only fact stored. See §8.
- Per-ZEV or per-participant storage quotas, virus scanning, and file types other than PDF.
- Automatic issue of annual statements at year end. Decided: the operator issues them explicitly (§4.1, §5.3).
- Anonymisation itself (#793). This spec states what the inbox needs from it (§6.3).
- Retrofitting the notification visibility rule for documents (§3, last paragraph).

## 3. Actors, permissions, and ZEV scope

| Actor | Capability |
|---|---|
| `admin` | Everything below, for every ZEV |
| manager grant (ADR 0027) | Reads the outbox of managed ZEVs; uploads, issues, delivers contracts, withdraws operator documents |
| viewer grant | Reads the outbox of viewable ZEVs; no writes |
| participant link | Reads the entries of every participant row linked to the account, with no `valid_to` condition and regardless of a disabled ZEV; downloads them |
| no account | Nothing, and nothing is lost: entries are addressed to the participant row and become visible when an account is linked |

**Scoping.** `DocumentViewSet` uses `ZevScopedQuerySetMixin` with `zev_lookup = "zev"`, `participant_path = "participant"` and `participant_access_survives_end = True`. One new mixin attribute is needed, `participant_survives_disabled_zev = False` by default, set to `True` here: `_participant_q` then omits `_not_disabled_q()`. The change is additive and every other viewset keeps today's behaviour. Writes use the existing managed-ZEV narrowing, so a participant or viewer reaches no write action (404 before view code runs).

**What a participant sees.** Rows where `participant__user` is the account, `withdrawn_at` is null. Superseded rows stay visible, marked as superseded, with the replacement linked. Managers and admins also see withdrawn rows, marked as such.

**An account linked to several participant rows** sees the union. Rows carry `zev` and `participant` so the UI can group.

**Relinking.** The inbox belongs to the participant row, not the account. Linking a different account to a row (`link_account`) therefore gives that account the row's history. This is intended (the row *is* the relationship) and is audited by the existing link events; see §8.

**Notifications.** The notification center (SPEC-2026-11-notification-center §3) hides participant notices once the link ends. This spec does **not** change that: a notification is an event for current members, the inbox is the durable record. The §3 bullet "Document inbox (#862). Not built" of that spec is updated to say so when phase 5 lands.

**Frontend.** Participant route `/documents` inside `ProtectedRoute`; manager outbox is a tab of the existing invoices hub (§7.2). No change to role gating.

## 4. Data model

New Django app `inbox` (`backend/inbox/`, registered in `INSTALLED_APPS`). One model; documents are immutable once delivered. Only `superseded_*` and `withdrawn_*` ever change.

### 4.1 `DeliveredDocument`

**Model:** `inbox.models.DeliveredDocument`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | PK |
| `zev` | `FK(zev.Zev, CASCADE)` | — | `related_name="delivered_documents"`. Denormalised copy of `participant.zev`, set in `save()` as `ContractIssue.save` does. `CASCADE`, unlike `ContractIssue.zev`: once the ZEV is purged nobody is left who could reach the document, and the purge erases what is under a ZEV (§4.2) |
| `participant` | `FK(zev.Participant, SET_NULL)` | — | `null=True`, `related_name="delivered_documents"`. `SET_NULL`, never `CASCADE`: deleting a participant must not delete what was delivered (#793) |
| `kind` | `CharField(32)` | — | `DocumentKind` choices: `invoice`, `contract`, `annual_statement`, `financial_summary`, `tariff_overview`, `operator` |
| `title` | `CharField(200)` | — | Shown in the list. Invoice: invoice number; contract: document number; statement: localised title with the year; operator: the manager's title |
| `document_number` | `CharField(64)` | `""` | Invoice or contract number; blank otherwise |
| `period_start` / `period_end` | `DateField` | — | `null=True`. Invoice period, statement year (1 Jan – 31 Dec); blank for contract and operator documents |
| `file` | `FileField(upload_to=inbox_upload_to, max_length=255)` | `""` | `blank=True`, not null (Django stores an empty `FileField` as `""`). Stored copy; empty only for `kind=contract`, whose bytes stay in `ContractIssue.pdf` |
| `file_name` | `CharField(255)` | `""` | Download name, sanitised with `config.http.sanitize_filename` |
| `content_type` | `CharField(100)` | `"application/pdf"` | |
| `size_bytes` | `PositiveBigIntegerField` | — | |
| `sha256` | `CharField(64)` | — | Of the stored bytes; fixes "this is what was delivered" |
| `invoice` | `FK(invoices.Invoice, SET_NULL)` | — | `null=True`, `related_name="delivered_documents"` |
| `contract_issue` | `FK(invoices.ContractIssue, PROTECT)` | — | `null=True`, `related_name="delivered_documents"`. `PROTECT`: a contract row has no file, so a vanished issue would leave a document with no body |
| `delivered_at` | `DateTimeField` | `timezone.now` | Invoice: its `sent_at` |
| `delivered_by` | `FK(AUTH_USER_MODEL, SET_NULL)` | — | `null=True`; null for system deliveries (invoice email task) |
| `batch_id` | `UUIDField` | — | `null=True`, indexed. Groups the rows of one broadcast upload or one bulk issue |
| `superseded_at` | `DateTimeField` | — | `null=True` |
| `superseded_by` | `FK("self", SET_NULL)` | — | `null=True`, `related_name="supersedes"` |
| `withdrawn_at` | `DateTimeField` | — | `null=True`; operator documents only |
| `withdrawn_by` | `FK(AUTH_USER_MODEL, SET_NULL)` | — | `null=True` |

**Meta:** `ordering = ["-delivered_at", "id"]`; indexes on `(participant, -delivered_at)` and `(zev, kind, -delivered_at)`.

**Constraints:**

- `inbox_document_has_one_body`: `CheckConstraint` — `kind="contract"` ⇔ `contract_issue` not null and `file=""`; every other kind has a non-empty `file`.
- `inbox_one_per_invoice`: `UniqueConstraint(fields=["invoice"], condition=Q(invoice__isnull=False))`. Delivery is idempotent: a resent email does not add a row.
- `inbox_one_per_contract_issue`: `UniqueConstraint(fields=["contract_issue", "participant"], condition=Q(contract_issue__isnull=False))`.
- `inbox_one_current_report`: `UniqueConstraint(fields=["participant", "kind", "period_start", "period_end"], condition=Q(kind__in=[annual_statement, financial_summary], superseded_at__isnull=True))`. Re-issuing a year supersedes the earlier one instead of duplicating it.
- `inbox_one_current_tariff_overview`: `UniqueConstraint(fields=["participant", "kind"], condition=Q(kind=tariff_overview, superseded_at__isnull=True))`. The overview has no period, and NULL periods compare as distinct, so it needs its own key.

**Why a copy for invoices and reports, a reference for contracts.** The invoice PDF is not stable: `approve_invoice` clears it, `generate-pdf` and the email task re-render it. The inbox therefore stores its own copy of the bytes that were delivered (for an emailed invoice, the exact attachment). `ContractIssue` is already an immutable snapshot (`BinaryField`, versioned), so a second copy would only be able to disagree with it.

**Methods.**

- `is_current` — `superseded_at is None and withdrawn_at is None`.
- `open_file()` — returns a binary file object: `file.open("rb")` or `io.BytesIO(contract_issue.pdf)`.

**Serializer:** `DeliveredDocumentSerializer` — fields `id, zev, zev_name, participant, participant_name, kind, title, document_number, period_start, period_end, file_name, size_bytes, sha256, delivered_at, delivered_by_name, superseded_at, superseded_by, withdrawn_at, batch_id, invoice, contract_issue`. All read-only, plus `invoice_status` (the source invoice's raw status, `null` for other kinds, so a cancelled invoice reads as cancelled). A participant only ever receives their own rows, so `participant_name` is their own name.

### 4.2 Retention and storage

Files are archival records: they are not touched by the privacy sweep, and the privacy-sweep spec stays unchanged. A ZEV purge (`zev.purge.purge_zev`) deletes the rows by cascade and, after commit, the stored files of those rows (a file shared by a broadcast is deleted once); `deleted_counts` gains `delivered_documents`. Storage is `MEDIA_ROOT/inbox/documents/<zev_id>/<uuid>.pdf`, never served from a media URL; every download goes through the API (§5.1). A broadcast upload writes **one** file and N rows pointing at it, so a deletion of a row never deletes a file another row still uses: `inbox.services.remove_file_if_unreferenced()` checks references first.

## 5. API contracts

New router `/api/v1/inbox/`, registered in `config/urls.py`.

### 5.1 Read: participant inbox and manager outbox

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/inbox/documents/` | GET | `IsAuthenticated` + scoping | Paginated list. Filters: `kind` (repeatable), `participant_id`, `zev_id`, `year` (matches `period_start` year or `delivered_at` year), `include_superseded` (default true), `include_withdrawn` (managers only; ignored for participants). Ordered newest first |
| `/api/v1/inbox/documents/{id}/` | GET | same | Detail |
| `/api/v1/inbox/documents/{id}/file/` | GET | same | `FileResponse`, `Content-Type: application/pdf`, `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`. 404 when out of scope or withdrawn (for participants). Downloads are **not** audited: that would be the read receipt decided against in §8 |

The list for a participant is a single indexed query on `participant__user`. It is not a union over the invoice, contract and report tables.

### 5.2 Write: operator documents

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/inbox/documents/` | POST (`multipart/form-data`) | manager of `zev` | Deliver an operator document. Fields: `zev` (required), `title` (required, ≤200), `file` (required), `audience` (`all` \| `selected`), `participant_ids` (required when `selected`), `notify` (bool, default `true`) |
| `/api/v1/inbox/documents/{id}/withdraw/` | POST | manager of the row's ZEV | Sets `withdrawn_at` / `withdrawn_by` on an `operator` row; any other kind → 400. Idempotent |

Validation for `POST`:

- `file`: `%PDF-` magic bytes in the first 5 bytes, size ≤ `INBOX_MAX_UPLOAD_BYTES` (default `10 * 1024 * 1024`), non-empty. The filename is only a suggestion and is sanitised; the content type is set by the server, never taken from the client.
- `audience="all"`: one row for every participant of the ZEV whose link is current **now** and who is not anonymised. A participant who joins later gets nothing (same rule as notification recipients).
- `selected`: every id must belong to `zev`; otherwise 400 naming the field, not the other ZEV.
- The ZEV must not be disabled (`assert_zev_not_disabled`).
- Response `201`: `{ batch_id, delivered: <n>, without_account: <m>, documents: [...] }`. `without_account` counts rows whose participant has no linked account, so the manager sees "3 of 12 will see this once an account is linked".

### 5.3 Write: issue reports, deliver a contract

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/inbox/issue/annual-statement/` | POST | manager of `zev` | Body `{ zev, year, participant_ids? , notify? }`; omitted `participant_ids` = every participant with billed invoices that year. Renders with the existing `generate_annual_statement_pdf(..., sent_only=True)` and stores the bytes. Re-issuing a year supersedes the earlier row |
| `/api/v1/inbox/issue/financial-summary/` | POST | manager of `zev` | Same, for producer participants (existing eligibility rule of `FinancialSummaryView`) |
| `/api/v1/inbox/issue/tariff-overview/` | POST | manager of `zev` | Body `{ zev, notify? }`; delivers the current tariff overview to every current participant |
| `/api/v1/inbox/documents/deliver-contract/` | POST | manager of `zev` | Body `{ contract_issue }`; delivers that stored version to its participant. Refuses a version that is not the participant's latest (409) so an outdated contract is not handed over |

**Contracts are delivered explicitly, not on issue.** A `ContractIssue` is minted whenever a manager downloads the contract (`issue_contract_pdf` in the participant `contract` action), including to preview or print it for signing. Delivering at that moment would put a contract into the participant's inbox before the operator has handed it over. (This refines #862, which proposed delivery "when a `ContractIssue` version is issued".)

Responses are the same shape as §5.2. All four are idempotent for the same (participant, kind, period): a second call supersedes.

### 5.4 Links already sent out

- `GET /api/v1/public/invoices/<prefix>/pdf/` (`views_public.public_invoice_pdf`) serves the invoice's **delivered** snapshot when one exists; with none (an invoice sent before the backfill), it keeps today's behaviour. The token still resolves to the invoice; the inbox row is looked up through `DeliveredDocument.invoice`.
- The invoice email template variable set gains `{inbox_url}` (`{FRONTEND_URL}/documents/<id>`) for participants with an account. The attachment is unchanged.

### 5.5 Phase 6: removed for participants

After the cut-over, a participant caller gets 404 (the existing scoping answer) from:

- `GET /api/v1/invoices/invoices/`, `/{id}/`, `/{id}/pdf/`;
- `GET /api/v1/invoices/invoices/annual-statement/`, `/financial-summary/`, `/tariff-overview/` as self-service (`_self_service` in `views_reports.py`).

Managers and admins keep every one of these. `participant_visible`, `participant_access_survives_end` and `sent_to_participant()` remain, because they serve the MCP tools and `explain_invoice` until those are moved (§6.4). The *My invoices* data comes from the inbox.

## 6. Async and integration behavior

### 6.1 `inbox.services`

- `deliver(*, participant, kind, title, body=None, stored=None, file_name="", delivered_by=None, batch_id=None, invoice=None, contract_issue=None, period=None, document_number="", delivered_at=None) -> (DeliveredDocument, created)`. Give exactly one of `body` (bytes, stored under a server-chosen name) and `stored` (a `StoredFile` from `store_file()`, so a broadcast writes one file for many rows); a contract takes neither and a `contract_issue`. Computes `sha256`, creates the row and records the audit event in one transaction. Idempotent for an invoice and a contract version: the second call returns `(existing, False)`. A report kind with a current row for the period supersedes it. A lost race on a constraint returns the winner.
- `store_file(zev, body, file_name)`, `discard_file(name)`, `remove_file_if_unreferenced(name)`.
- `supersede(old, new, *, user=None)` — links an already delivered pair (a corrected invoice); idempotent, refuses a self-link. The report case is inside `deliver()`: it sets `old.superseded_at`, inserts `new`, then sets `old.superseded_by`; setting the flag first is what lets the `inbox_one_current_report` constraint hold.
- `withdraw(document, by)`.
- `deliver()` writes the file **before** the row and removes it again if the row insert fails, so an orphaned file cannot outlive a failed delivery (the `save_invoice_pdf` pattern). A file passed in as `stored` stays the caller's to discard. Audit events use category `participant` and action types `inbox.document.delivered`, `.superseded` and `.withdrawn`; no new audit category is added, so no audit migration or filter change.

### 6.2 Producers

| Source | Hook | Behaviour |
|---|---|---|
| Invoice emailed | `workflow.record_email_delivery` when `first_delivery` | `deliver(kind="invoice", body=<the attachment bytes>, delivered_at=sent_at)`. The email task already reads `invoice.pdf_file`; it passes those same bytes. A resent email does not create a row |
| Invoice marked sent by hand | `workflow.mark_invoice_sent` | Delivers `invoice.pdf_file`, rendering it first with `save_invoice_pdf` when missing. If rendering fails the transition still succeeds (the invoice is the deliverable), the failure is audited, and `inbox_backfill` picks it up |
| Invoice cancelled and replaced | `cancel_invoice` and the replacement link (`replaces` / `replaced_by`, #388) | When the replacement is **sent**, `supersede(old_row, new_row)`. A cancelled invoice that was never replaced stays in the inbox, marked cancelled through its invoice status (`invoice_status` in the serializer). Nothing is deleted (ADR 0037) |
| Contract | `POST /inbox/documents/deliver-contract/` | `deliver(kind="contract", contract_issue=...)`; no copy |
| Reports | `POST /inbox/issue/*` | `deliver(...)` / `supersede(...)` |
| Operator document | `POST /inbox/documents/` | one `deliver` per recipient, same stored file |

Every producer is wrapped like the notification producers (`@best_effort`): a failure to deliver is audited and never rolls back the workflow transition it hangs off.

### 6.3 Interaction with anonymisation (#793)

Decision for this spec, to be honoured by #793:

- Anonymising a participant **leaves the inbox rows and files untouched**: they are the accounting record, as `ContractIssue` already is.
- It unlinks the account (`Participant.user = None`), which ends all access, since visibility is `participant__user`.
- `DeliveredDocument.title` for `operator` rows may contain a name; `title` of invoice, contract and report rows does not (it is a number or a localised type and year).
- The PDF bytes carry the participant's name. That is stated in #793's response copy; it is not a defect of the inbox.

### 6.4 Backups, transfer, MCP

- **Backups.** `inbox.DeliveredDocument` is a ZEV-scoped part (`ZevPart("inbox.DeliveredDocument", "zev")`) in `backups/registry.py`, and `("inbox.DeliveredDocument", "file", "zev")` joins the file-field list beside `invoices.Invoice`. The coverage test (`backups/test_archive.py`) fails until both are in place, as intended. The section `delivered_documents` comes after `invoices` and `contract_issues`, which its rows point at. A per-ZEV restore gains the overridable conflict `delivered_document_deleted` (a delivered document the backup lacks would be deleted, as for `contract_issue_deleted`), with the new key in `RestoreConflictKind` and in the four locale files.
- **Transfer archive (increment 1b).** `FORMAT_VERSION` 10 → 11 adds `delivered_documents` (rows and files). Not part of increment 1: the transfer archive carries neither contracts nor accounts, so remapping participants and invoices needs its own design pass. Version 10 archives import unchanged and create no rows; a re-imported ZEV re-derives nothing, because delivery is a fact, not a derivation.
- **MCP.** The read-only participant tools (`find_invoices`, `explain_invoice`) keep working through the live endpoints in phases 1–5. Phase 6 either leaves them on `participant_visible` or moves them to the inbox; decided in the phase 6 PR.

### 6.5 Notifications and email

- `invoice.sent` (exists) gains `document_id` in its payload so the bell links to `/documents/<id>`. No second event for the same fact.
- New registry type `document.delivered` (audience `participant`, not mandatory) for `contract`, `annual_statement`, `financial_summary`, `tariff_overview`, `operator`; payload `{ document_id, kind, title }`; `dedupe_key = f"document.delivered:{document.pk}"`.
- Email for non-invoice documents is **opt-in per delivery** (`notify`), link-only and without an attachment: new `EmailTemplate` type `document_delivered` with defaults `DEFAULT_DOCUMENT_EMAIL_SUBJECT` / `_BODY` in `invoices/models.py`, edited in the admin console beside the others. Recipients without an email address are skipped and counted in the response. Sent through the existing email task and `EmailLog`.

### 6.6 Backfill

`python manage.py openzev_inbox_backfill [--zev ID] [--dry-run]`, also callable as a Celery task. For each invoice matching `sent_to_participant()` with a stored `pdf_file` and no row, it delivers with `delivered_at = sent_at or approved_at`. Invoices whose file is missing from storage are listed in the report and skipped; they remain reachable through the live path until phase 6, and the **cut-over PR is blocked until the report is empty or accepted by the operator**. It does not touch contracts (explicit delivery) or reports (never issued before). Idempotent by the unique constraints.

## 7. Frontend

### 7.1 Participant *Documents* page

**File:** `frontend/src/pages/DocumentsPage.tsx`

- Route `/documents` (participant shell); *My invoices* (`MyInvoicesPage.tsx`) is kept in phases 1–5 and becomes a filtered view of this page in phase 6.
- Query: `useQuery({ queryKey: queryKeys.inbox.list(filters), queryFn: listInboxDocuments })`.
- A list grouped by year, a kind filter (chips), a ZEV filter shown only when the account has more than one participant row. Per row: icon by kind, title, delivered date, status badge (*Superseded*, *Cancelled* for an invoice, *Withdrawn* for managers), download action. An invoice row links to the existing invoice detail while the live path exists.
- Container: a page with a list and download actions, no dialogs, per the catalogue in `2026-10-ui-patterns-and-component-catalog.md`. Empty state: "Nothing has been delivered to you yet."
- The annual statement and financial summary cards on the participant *Reports* page (`ParticipantYearDocuments.tsx`) read the issued row for the chosen year, falling back to on-demand rendering until phase 6, with an explicit *Issued on …* line when delivered.
- Mobile (~400px): single column, download as a full-width row action.

### 7.2 Manager outbox and upload

**Files:** `frontend/src/features/inbox/OutboxTab.tsx`, `UploadDocumentDialog.tsx`, `IssueReportsDialog.tsx`.

- A *Delivered documents* tab on the invoices hub for managers: the same list with participant, kind, year and withdrawn filters, a column for delivery date, and a "no account yet" badge. A manager can answer "did Anna get her statement?" from here.
- *Upload document* (dialog; one task, a few fields): title, file, audience (everyone in the ZEV / selected participants), a *Notify by email* checkbox. The result states how many rows were created and how many recipients have no account.
- *Issue annual statements* (dialog): year, all or selected participants, the same notify checkbox; reuses `YearPicker`.
- Deliver contract: an action on the participant's contract versions in the existing contract UI, never automatic.
- All user-facing text in the locale files (`frontend/src/i18n/locales`), a new `inbox` namespace in `de`, `fr`, `it` and `en`.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type DocumentKind =
  | 'invoice' | 'contract' | 'annual_statement'
  | 'financial_summary' | 'tariff_overview' | 'operator'

export interface DeliveredDocument {
  id: string
  zev: string | null
  zev_name: string
  participant: string | null
  participant_name: string | null   // null for participant callers
  kind: DocumentKind
  title: string
  document_number: string
  period_start: string | null
  period_end: string | null
  file_name: string
  size_bytes: number | null
  sha256: string
  delivered_at: string
  delivered_by_name: string | null
  superseded_at: string | null
  superseded_by: string | null
  withdrawn_at: string | null
  batch_id: string | null
  invoice: string | null
  invoice_status: InvoiceStatus | null
  contract_issue: string | null
}

export interface DeliveryResult {
  batch_id: string
  delivered: number
  without_account: number
  documents: DeliveredDocument[]
}
```

### API client functions

**File:** `frontend/src/lib/api/inbox.ts`

| Function | Method | Endpoint |
|---|---|---|
| `listInboxDocuments(filters)` | GET | `/inbox/documents/` |
| `getInboxDocument(id)` | GET | `/inbox/documents/{id}/` |
| `downloadInboxDocument(id)` | GET | `/inbox/documents/{id}/file/` |
| `uploadInboxDocument(form)` | POST | `/inbox/documents/` |
| `withdrawInboxDocument(id)` | POST | `/inbox/documents/{id}/withdraw/` |
| `issueAnnualStatements(body)` | POST | `/inbox/issue/annual-statement/` |
| `issueFinancialSummaries(body)` | POST | `/inbox/issue/financial-summary/` |
| `issueTariffOverview(body)` | POST | `/inbox/issue/tariff-overview/` |
| `deliverContract(body)` | POST | `/inbox/documents/deliver-contract/` |

## 8. Decisions, risks and mitigations

Decisions the issue left open, and how this spec settles them:

| Question (#862) | Decision | Why |
|---|---|---|
| Retention and anonymisation (#793) | Files stay; anonymisation unlinks the account (§6.3) | Accounting retention wins over metadata; the account link is what grants access |
| Annual statement automatic or issued | **Issued by the operator**, bulk action available | Figures can still be corrected after year end; a wrong statement must not arrive unreviewed |
| Read receipts | **No.** Only `delivered_at`; the outbox shows email delivery from `EmailLog` | Tracking when a person opened a document is monitoring; "delivered" is enough for a dispute about whether something was sent |
| Upload limits and types | PDF only, `%PDF-` magic bytes, 10 MiB (`INBOX_MAX_UPLOAD_BYTES`) | One safe, previewable type; no active content to serve |
| Notification | `invoice.sent` reused; `document.delivered` new; email opt-in, link-only, no attachment | The invoice email already attaches the PDF; a second mail for the same fact is noise |
| Contract delivery | Explicit action, not on issue (§5.3) | `ContractIssue` also records manager previews |

| Risk | Impact | Mitigation |
|---|---|---|
| A document sent to the wrong participant cannot be taken back (invoices) | Medium | Operator documents can be withdrawn (hidden from participants, audited, file kept). Invoices and reports are corrected by supersession, never withdrawn (ADR 0037) |
| Relinking an account gives a new person the row's history | Medium | Existing link / unlink audit events; the unlink dialog states that documents stay with the participant row; no automatic relinking exists |
| An emailed PDF and the stored copy diverge | High | The stored bytes are the email attachment bytes, `sha256` is recorded, and a test asserts equality |
| `generate-pdf` on a sent invoice changes `Invoice.pdf_file` | Medium | The inbox no longer reads `pdf_file` for participants, so the delivered file cannot change; the manager keeps the live PDF |
| A participant's browser or proxy caches a downloaded document | Low | `Cache-Control: private, no-store`; `nosniff`; `attachment` |
| Disk growth from uploads | Low | 10 MiB limit, one file per broadcast; quotas out of scope |
| A hidden deletion path destroys a file another row uses | Medium | `remove_file_if_unreferenced()`; the only deletion is the failed-insert rollback |
| Phase 6 breaks the dashboard card, MCP tools or saved links | High | Separate release; the backfill report gates it; the invoice link and public page already resolve to the inbox (phase 5) |
| The disabled-ZEV exception in the mixin is copied elsewhere | Medium | Off by default, named for what it does, and the inbox is the only user; a scoping regression test pins every other viewset |

## 9. Test plan

All counts are planned; the final numbers replace them when each phase lands.

### Backend — `inbox/test_models.py` (8, increment 1)

`test_contract_row_has_no_file_and_references_issue`, `test_other_kinds_require_a_file`, `test_one_row_per_invoice`, `test_one_current_report_per_participant_kind_period` (superseded rows excluded, other year and kind independent), `test_one_current_tariff_overview_per_participant`, `test_zev_is_derived_from_participant`, `test_participant_delete_keeps_the_row`, `test_open_file_reads_the_stored_copy_or_the_contract_bytes`.

### Backend — `inbox/test_services.py` (12, increment 1)

`test_deliver_stores_bytes_and_sha256`, `test_deliver_is_idempotent_for_invoice`, `test_deliver_contract_references_the_issue_without_a_copy`, `test_a_contract_with_a_body_or_an_other_kind_without_one_is_refused`, `test_deliver_removes_the_file_when_the_row_cannot_be_written`, `test_redelivering_a_report_supersedes_the_earlier_one`, `test_a_shared_stored_file_backs_several_rows_and_survives_deleting_one`, `test_audit_event_written_per_delivery`, `test_supersede_links_both_rows_and_is_idempotent`, `test_a_document_cannot_supersede_itself`, `test_withdraw_only_operator_documents`, `test_withdraw_hides_but_keeps_row_and_file_and_is_idempotent`.

### Backend — `inbox/test_visibility.py` (19, increment 1)

| Test | Asserts |
|---|---|
| `test_participant_sees_only_own_rows` | tenant isolation (list, detail, file) |
| `test_account_with_two_participant_rows_sees_both` | union, `zev_id` narrows |
| `test_row_stays_after_valid_to_passes` | no end date |
| `test_row_stays_when_zev_is_disabled` | the new mixin attribute |
| `test_other_viewsets_still_hide_a_disabled_zev` | regression: invoices stay hidden |
| `test_row_appears_when_account_is_linked_later` | addressed to the participant |
| `test_unlinking_the_account_removes_access` | `participant__user` |
| `test_participant_cannot_see_withdrawn_but_manager_can` | withdrawn handling |
| `test_participant_include_withdrawn_does_not_widen` | filters only narrow |
| `test_superseded_row_visible_with_link` | `superseded_by`, `include_superseded` |
| `test_manager_outbox_covers_the_zev_and_filters` | outbox, `participant_id`, `kind` |
| `test_viewer_reads_but_cannot_write` | no write route (405) |
| `test_manager_of_another_zev_sees_nothing` | 404 |
| `test_admin_sees_all` | |
| `test_anonymous_is_refused` | 401 |
| `test_bad_filters_are_validation_errors` | `kind`, `year`, `participant_id` |
| `test_year_filter_matches_period_or_delivery_year` | |
| `test_download_headers` | attachment, nosniff, no-store, exact bytes |
| `test_contract_download_serves_the_issue_bytes` | reference, no copy |

### Backend — `backups/test_inbox_documents.py` (4) and `zev/test_purge.py` (1), increment 1

`test_rows_and_files_travel_and_contracts_go_by_reference`, `test_another_zev_does_not_carry_the_documents`, `test_restoring_brings_documents_back_with_their_bytes`, `test_a_document_the_restore_would_delete_needs_force`; `test_deletes_delivered_documents_and_their_files_once` (a shared file counts once). Kept out of the shared `build_world` fixture, whose counts other backup tests pin.

### Backend — `inbox/test_api_upload.py` (≈10)

`test_upload_all_creates_a_row_per_current_participant`, `test_upload_selected_rejects_participant_of_other_zev`, `test_upload_rejects_non_pdf_magic_bytes`, `test_upload_rejects_oversize`, `test_upload_rejects_empty`, `test_upload_ignores_client_content_type`, `test_upload_refused_for_disabled_zev`, `test_later_participant_gets_no_backlog`, `test_response_counts_recipients_without_account`, `test_download_headers` (attachment, nosniff, no-store).

### Backend — `inbox/test_producers.py` (≈12)

`test_email_delivery_delivers_attachment_bytes`, `test_stored_bytes_equal_email_attachment`, `test_resent_email_does_not_add_a_row`, `test_mark_sent_delivers_stored_pdf`, `test_mark_sent_renders_missing_pdf`, `test_mark_sent_survives_render_failure`, `test_generate_pdf_after_sending_does_not_change_the_delivered_file`, `test_replacement_supersedes_earlier_row`, `test_cancelled_without_replacement_keeps_row`, `test_deliver_contract_references_issue_without_copy`, `test_deliver_contract_refuses_outdated_version`, `test_issue_annual_statement_supersedes_on_reissue`.

### Backend — other

- `inbox/test_backfill.py` (≈5): creates rows for sent invoices, skips missing files and reports them, `--dry-run` writes nothing, idempotent, `delivered_at` equals `sent_at`.
- `backups/test_archive.py`: the existing coverage tests pass with the model and file field registered (increment 1).
- `zev/transfer` (increment 1b): export / import round trip at format 11; a v10 archive imports without rows (≈3).
- `notifications/test_producers.py`: `invoice.sent` payload carries `document_id`; `document.delivered` dedupes (≈3).
- `invoices/test_public_invoice_access.py`: public PDF serves the delivered snapshot, falls back when none (≈2).
- Phase 6: `invoices/test_participant_invoice_visibility.py` is rewritten so a participant gets 404 on every live endpoint and managers are unchanged (≈6 changed).

### Frontend

- Unit tests for the kind / year grouping helper and the upload form validation (extension and size hints are advisory; the server decides).
- `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`, `npm run build`.
- Screenshots of the participant page and outbox in the dev stack, including a ~400px viewport; a `ui-review` pass before phase 4 merges.

### Acceptance criteria

- [ ] An invoice that is emailed appears in the participant's inbox with the exact bytes of the attachment, and re-rendering the invoice PDF later does not change what the inbox serves.
- [ ] A cancelled-and-replaced invoice shows the earlier entry as superseded with a link to the replacement; nothing is deleted.
- [ ] A participant whose link has ended, or whose ZEV is disabled, can still list and download every entry delivered to them, and sees no live data.
- [ ] An entry delivered before an account existed is visible as soon as an account is linked.
- [ ] An operator can upload one PDF to everyone in the ZEV or to selected participants and sees how many recipients have no account; a non-PDF or an oversize file is refused with a field error.
- [ ] A contract enters the inbox only through the explicit action; downloading a contract as a manager delivers nothing.
- [ ] An annual statement enters the inbox only when the operator issues it, and re-issuing supersedes the earlier one.
- [ ] A manager can see what was delivered to whom and when, and can withdraw an operator document without losing the file.
- [ ] The backup and transfer archives contain the rows and files and restore them; the backup coverage test passes.
- [ ] Phase 6 only: participant calls to the live invoice and report endpoints return 404; managers and admins are unchanged.
- [ ] The user guide chapter, `2026-03-invoice-lifecycle-and-communication.md`, `2026-03-community-and-access.md`, `2026-08-zev-transfer-archive.md`, `2026-11-notification-center.md` and the `docs/specs/README.md` index are updated in the phase that changes them.
