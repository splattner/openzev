# Feature Spec: Participant document inbox

- Spec ID: SPEC-2026-11-participant-document-inbox
- Status: Implemented (phases 1–6b; 6b ships a release after the rest)
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-11-05
- Target Release: next minor (phases 1–6a), the release after (phase 6b)
- Related Issues: [#862](https://github.com/splattner/openzev/issues/862); see also #761 (parties vs. accounts, shipped), #861 (draft invoices, shipped), #793 (anonymisation, open), #989 (notification center, shipped)
- Related ADRs: [ADR 0045](../adr/0045-delivered-documents-are-immutable-and-addressed-to-the-participant.md), [ADR 0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md), [ADR 0027](../adr/0027-per-zev-access-grants.md)
- Impacted Areas: backend | frontend | async jobs | docs

### Increments

| # | Delivered | PRs |
|---|---|---|
| 0 | This spec and ADR 0045 | — |
| 1 | `inbox` app: model, `deliver()` service, scoping, read and outbox API, backups (incl. per-ZEV restore), ZEV purge, audit | — |
| 1b | Transfer archive format 11 (`delivered_documents`) | stacked on #1206 |
| 2 | Producers: invoice sent, explicit contract delivery, backfill command | stacked on #1207 |
| 3 | Operator documents (upload, withdraw), issued annual statement / financial summary / tariff overview | #1209, stacked on #1208 |
| 4 | Frontend: participant *My documents* page, manager *Delivered documents* tab, upload and issue dialogs, deliver-contract action; `deliver-contract` also by participant; demo seed | stacked on #1209 |
| 5 | Links and the bell: the public invoice PDF serves the delivered snapshot, `{inbox_url}` in the invoice email, `invoice.sent` carries `document_id`, new `document.delivered` notification | stacked on #1210 |
| 5b | Email for documents: opt-in `notify` on upload, issue and deliver-contract (checkbox on upload and issue), `document_delivered` template | stacked on #1213 |
| 6a | Credit notes: kind `credit_note`, delivered when the credit note's PDF first exists, backfill, bell | stacked on #1214 |
| 6b | Cut-over (follow-up release): participants lose the live invoice, credit note and report endpoints; *My invoices*, the dashboard card and *Annual statement* read the inbox, whose invoice and credit note rows carry live figures | stacked on #1215 |

Each increment is its own PR and can ship alone. Phases 1–6a add; only phase 6b removes anything.

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
| Notifications | `invoice.sent` links to the inbox entry; new `document.delivered` for every other kind; opt-in email for documents (increment 5b) |
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

**Frontend.** Participant route `/me/documents` (the participant pages all live under `/me/`) inside `ProtectedRoute`; manager outbox is a tab of the existing invoices hub (§7.2). No change to role gating.

## 4. Data model

New Django app `inbox` (`backend/inbox/`, registered in `INSTALLED_APPS`). One model; documents are immutable once delivered. Only `superseded_*` and `withdrawn_*` ever change.

### 4.1 `DeliveredDocument`

**Model:** `inbox.models.DeliveredDocument`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` | `uuid4` | PK |
| `zev` | `FK(zev.Zev, CASCADE)` | — | `related_name="delivered_documents"`. Denormalised copy of `participant.zev`, set in `save()` as `ContractIssue.save` does. `CASCADE`, unlike `ContractIssue.zev`: once the ZEV is purged nobody is left who could reach the document, and the purge erases what is under a ZEV (§4.2) |
| `participant` | `FK(zev.Participant, SET_NULL)` | — | `null=True`, `related_name="delivered_documents"`. `SET_NULL`, never `CASCADE`: deleting a participant must not delete what was delivered (#793) |
| `kind` | `CharField(32)` | — | `DocumentKind` choices: `invoice`, `contract`, `annual_statement`, `financial_summary`, `tariff_overview`, `credit_note`, `operator` |
| `title` | `CharField(200)` | — | Shown in the list. Invoice: invoice number; contract: document number; statement: localised title with the year; operator: the manager's title |
| `document_number` | `CharField(64)` | `""` | Invoice or contract number; blank otherwise |
| `period_start` / `period_end` | `DateField` | — | `null=True`. Invoice period, statement year (1 Jan – 31 Dec); blank for contract, credit note and operator documents (a credit note sorts under the year it was issued) |
| `file` | `FileField(upload_to=inbox_upload_to, max_length=255)` | `""` | `blank=True`, not null (Django stores an empty `FileField` as `""`). Stored copy; empty only for a contract held by reference, whose bytes stay in `ContractIssue.pdf` |
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

- `inbox_document_has_one_body`: `CheckConstraint` — either `kind="contract"` with `contract_issue` not null and `file=""`, or `contract_issue` null and a non-empty `file`. The second branch also holds a contract that arrived through a transfer archive (migration `0002`).
- `inbox_one_per_invoice`: `UniqueConstraint(fields=["invoice"], condition=Q(invoice__isnull=False))`. Delivery is idempotent: a resent email does not add a row.
- `inbox_one_per_credit_note`: `UniqueConstraint(fields=["zev", "document_number"], condition=Q(kind=credit_note))` (migration `0003`). A credit note is keyed by its number, which is unique per ZEV, and carries no foreign key to `Credit`: a document is a fact and survives the row it came from. Delivery is idempotent on it, so re-rendering the credit note's PDF never replaces the delivered copy.
- `inbox_one_per_contract_issue`: `UniqueConstraint(fields=["contract_issue", "participant"], condition=Q(contract_issue__isnull=False))`.
- `inbox_one_current_report`: `UniqueConstraint(fields=["participant", "kind", "period_start", "period_end"], condition=Q(kind__in=[annual_statement, financial_summary], superseded_at__isnull=True))`. Re-issuing a year supersedes the earlier one instead of duplicating it.
- `inbox_one_current_tariff_overview`: `UniqueConstraint(fields=["participant", "kind"], condition=Q(kind=tariff_overview, superseded_at__isnull=True))`. The overview has no period, and NULL periods compare as distinct, so it needs its own key.

**Why a copy for invoices and reports, a reference for contracts.** The invoice PDF is not stable: `approve_invoice` clears it, `generate-pdf` and the email task re-render it. The inbox therefore stores its own copy of the bytes that were delivered (for an emailed invoice, the exact attachment). `ContractIssue` is already an immutable snapshot (`BinaryField`, versioned), so a second copy would only be able to disagree with it.

**Methods.**

- `is_current` — `superseded_at is None and withdrawn_at is None`.
- `open_file()` — returns a binary file object: `file.open("rb")` or `io.BytesIO(contract_issue.pdf)`.

**Serializer:** `DeliveredDocumentSerializer` — fields `id, zev, zev_name, participant, participant_name, kind, title, document_number, period_start, period_end, file_name, size_bytes, sha256, delivered_at, delivered_by_name, superseded_at, superseded_by, withdrawn_at, batch_id, invoice, contract_issue`. All read-only, plus `invoice_status` (the source invoice's raw status, `null` for other kinds, so a cancelled invoice reads as cancelled) and, since phase 6b, the live figures `invoice_figures` and `credit_figures` (below). A participant only ever receives their own rows, so `participant_name` is their own name.

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
| `/api/v1/inbox/documents/` | POST (`multipart/form-data`) | manager of `zev` | Deliver an operator document. Fields: `zev` (required), `title` (required, ≤200), `file` (required), `audience` (`all` \| `selected`, default `all`), `participant_ids` (required when `selected`), `notify` (boolean, default `false`: also email the participants, §6.5) |
| `/api/v1/inbox/documents/{id}/withdraw/` | POST | manager of the row's ZEV | Sets `withdrawn_at` / `withdrawn_by` on an `operator` row and answers 200 with the document; any other kind → 400. Idempotent. A participant, a viewer and a manager of another ZEV get 404; a disabled ZEV refuses a manager (400) but not an admin |

Validation for `POST`:

- `file`: `%PDF-` magic bytes in the first 5 bytes, size ≤ `INBOX_MAX_UPLOAD_BYTES` (default `10 * 1024 * 1024`), non-empty. The filename is only a suggestion and is sanitised; the content type is set by the server, never taken from the client.
- `audience="all"`: one row for every participant of the ZEV whose link is current **now** (`live_participant_q`; anonymisation, #793, does not exist yet and will have to leave its rows out of this set). No participant to deliver to → 400 on `audience`. A participant who joins later gets nothing (same rule as notification recipients).
- `selected`: every id must belong to `zev`; otherwise 400 naming the field, not the other ZEV.
- The ZEV must not be disabled (`assert_zev_not_disabled`).
- Response `201`: `{ batch_id, delivered: <n>, without_account: <m>, emailed: <e>, without_email: <w>, documents: [...] }`. `without_account` counts rows whose participant has no linked account, so the manager sees "3 of 12 will see this once an account is linked". `emailed` and `without_email` are 0 unless `notify` was set: emails queued, and recipients skipped for want of an address (§6.5).

### 5.3 Write: issue reports, deliver a contract

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `/api/v1/inbox/issue/annual-statement/` | POST | manager of `zev` | Body `{ zev, year, participant_ids?, notify? }`; omitted `participant_ids` = every participant with a billed invoice that year **that reached them** (`billed_invoices` and `sent_to_participant()`, because the statement is rendered with `sent_only=True` and would otherwise list nothing). Renders with the existing `generate_annual_statement_pdf(..., sent_only=True)` and stores the bytes. Re-issuing a year supersedes the earlier row |
| `/api/v1/inbox/issue/financial-summary/` | POST | manager of `zev` | Same, for producers. `FinancialSummaryView` has no eligibility rule of its own (it renders for whoever is named), so the inbox defines one from what the summary reports: a participant with a billed invoice in the year that carries a `feed_in` item or a `local_energy` item below zero (`issuing.summary_participant_ids`) |
| `/api/v1/inbox/issue/tariff-overview/` | POST | manager of `zev` | Body `{ zev, participant_ids?, notify? }`; delivers the tariff overview as of today (`scope=valid`) to every current participant, or to the named ones. It is rendered once and every row shares the file. Re-issuing supersedes each participant's earlier overview |
| `/api/v1/inbox/documents/deliver-contract/` | POST | manager of `zev` | Body `{ contract_issue }` **or** `{ participant }` (exactly one, else 400), plus optional `notify`; with `participant` it means that participant's latest issued version, and a participant with no issued contract answers 404. Delivers that stored version to its participant. Refuses a version that is not the participant's latest (409) so an outdated contract is not handed over. An unknown issue and one of another ZEV both answer 404; a disabled ZEV refuses a manager (400) but not an admin; delivering the same version again answers 200 with `delivered: 0`. The first delivery answers 201 |

**Contracts are delivered explicitly, not on issue.** A `ContractIssue` is minted whenever a manager downloads the contract (`issue_contract_pdf` in the participant `contract` action), including to preview or print it for signing. Delivering at that moment would put a contract into the participant's inbox before the operator has handed it over. (This refines #862, which proposed delivery "when a `ContractIssue` version is issued".)

Responses are the same shape as §5.2 (`201` when something was delivered). Naming participants of another ZEV, or participants with nothing to report for the year, is a 400 on `participant_ids`; so is a year where nobody is eligible. The three report endpoints supersede on a second call for the same (participant, kind, period); the contract endpoint is idempotent.

Everything is rendered before anything is written, in one transaction: a generator that fails delivers nothing and leaves no file behind. The calls are synchronous; a ZEV with very many participants would be better served by a task, which this spec does not yet need.

### 5.4 Links already sent out

- `GET /api/v1/public/invoices/<prefix>/pdf/` (`views_public.public_invoice_pdf`) serves the invoice's **delivered** snapshot when one exists; with none (an invoice sent before the backfill), it keeps today's behaviour. The token still resolves to the invoice; the inbox row is looked up through `DeliveredDocument.invoice`.
- The invoice email template variable set gains `{inbox_url}`: `{FRONTEND_URL}/me/documents` (`inbox.links.inbox_url`) for a participant with a login, empty otherwise. It points at the list, not at one entry, because the email is rendered before the invoice is delivered, so there is no row to name yet. It is in the field catalogue (`admin.emailTemplates.fields.inboxUrl`), not in the default body: stored templates and the shipped text keep reading as they do. The attachment is unchanged.

**Live figures (phase 6b).** The delivered file is a copy and never changes, but what a participant owes does. So that the pages that used to list live invoices keep their amounts, the serializer reads two read-only objects **from the invoice or credit at request time** and never stores them in the row (the file stays the immutable fact, ADR 0045):

| Field | Present for | Content |
|---|---|---|
| `invoice_figures` | rows with an `invoice` | `{status, due_date, total_chf, credit_applied_chf, amount_due_chf, paid_chf, outstanding_chf, open_data_impact_count}`: money as 2-decimal strings; `paid_chf` is the sum of the invoice's payments, `outstanding_chf` is `amount_due_chf − paid_chf` (`"0.00"` when cancelled); `open_data_impact_count` is how many unresolved reading corrections may have outdated the invoice (the count only: the import evidence stays with managers) |
| `credit_figures` | `credit_note` rows | `{amount_chf, remaining_chf, status, source_invoice_number, applied_to: [{invoice_number, amount_chf}]}`: found by `(zev, credit number)`; `applied_to` lists the applications that were not released; `null` when the credit note no longer exists |

Both are `null` otherwise. The list adds one query for the invoices' payments (`prefetch_related("invoice__payments")`), one for the open corrections (a subquery annotation) and, through `DeliveredDocumentListSerializer`, one for the credit notes of the page, so the query count does not grow with the rows.

### 5.5 Phase 6b: removed for participants

After the cut-over a participant reaches no live invoice, credit note or report. The viewsets have no participant path (`participant_path = None`, "a manager-only resource" in `ZevScopedQuerySetMixin`), which is the existing scoping answer rather than a new rule:

- `GET /api/v1/invoices/invoices/` is an empty list; `/{id}/`, `/{id}/pdf/` and the other detail routes are 404 (the actions that already demand a manager stay 403, `payments/` among them);
- `GET /api/v1/invoices/credits/` is an empty list and `credits/{id}/`, `credits/{id}/pdf/` are 404;
- `GET /api/v1/invoices/invoices/annual-statement/` and `/financial-summary/` answer a participant call with 404 `{"error": "Participant not found."}` (`_is_participant_call` in `views_reports.py`, which replaces `_self_service`): an account that only participates, a participant of the ZEV it names, and a former participant. The tariff overview never had a self-service branch. An account that never took part is still served as a manager (400 without ids, 403 for a ZEV it may not read). The `sent_only` argument of `generate_annual_statement_pdf` stays, for the inbox issuing.

This also holds for a manager who is a participant of another community: that community's invoices are not reachable live, and their own are in their inbox.

Managers and admins keep every route. `participant_visible` and `participant_access_survives_end` stay in `ZevScopedQuerySetMixin` (the inbox uses both); `sent_to_participant()` stays, because the inbox backfill and the annual statement decide by it.

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
| Invoice marked sent by hand | `workflow.mark_invoice_sent` | Delivers `invoice.pdf_file`, or a render from `generate_pdf` when it is missing (not stored on the invoice). If rendering fails the transition still succeeds (the invoice is the deliverable), the failure is audited, and `inbox_backfill` picks it up |
| Invoice cancelled | `cancel_invoice` | Nothing to do: a sent invoice that is cancelled stays in the inbox, marked cancelled through its invoice status (`invoice_status` in the serializer). Nothing is deleted (ADR 0037). There is no replacement link between invoices (a sent invoice is corrected by a credit note, `correct_invoice`), so `supersede()` has no invoice producer; it serves reports only |
| Credit note issued | `invoices.tasks.generate_credit_pdf_task`, after a successful render | `deliver(kind="credit_note", body=<the rendered bytes>, document_number=<credit number>, delivered_at=credit.created_at)` through `inbox.producers.deliver_credit_note`, which never raises. A credit note has no "sent" step: today a participant reads it from the moment it exists, so the first render that succeeds is the delivery. The row is made once (by number); a manager's re-render later does not touch it, and a failed render delivers nothing until a render succeeds. A failed delivery is audited like an invoice's. The participant gets a `document.delivered` notification when the row is new |
| Contract | `POST /inbox/documents/deliver-contract/` | `deliver(kind="contract", contract_issue=...)`; no copy. Title and document number are the contract's document number |
| Reports | `POST /inbox/issue/*` | `deliver(...)` / `supersede(...)` |
| Operator document | `POST /inbox/documents/` | one `deliver` per recipient, same stored file |

The two invoice producers live in `inbox/producers.py` (`deliver_sent_invoice`, which never raises): a failure to deliver is logged, audited as a `FAILED` `inbox.document.delivered` event on the invoice, and never rolls back the workflow transition it hangs off. `record_email_delivery(invoice, sent_at, *, document=None)` takes the attached bytes from the email task (which keeps what it attached), delivers on the first delivery whatever the status has become, and passes `delivered_at=sent_at`; a resend is a no-op. `mark_invoice_sent` delivers the stored PDF, or a render of the invoice from `generate_pdf` when there is none. The render is not stored on the invoice: `pdf_file` stays empty (cleared on approval, generated on request), so marking an invoice as sent changes nothing about the invoice's own PDF.

### 6.3 Interaction with anonymisation (#793)

Decision for this spec, to be honoured by #793:

- Anonymising a participant **leaves the inbox rows and files untouched**: they are the accounting record, as `ContractIssue` already is.
- It unlinks the account (`Participant.user = None`), which ends all access, since visibility is `participant__user`.
- `DeliveredDocument.title` for `operator` rows may contain a name; `title` of invoice, contract and report rows does not (it is a number or a localised type and year).
- The PDF bytes carry the participant's name. That is stated in #793's response copy; it is not a defect of the inbox.

### 6.4 Backups, transfer, MCP

- **Backups.** `inbox.DeliveredDocument` is a ZEV-scoped part (`ZevPart("inbox.DeliveredDocument", "zev")`) in `backups/registry.py`, and `("inbox.DeliveredDocument", "file", "zev")` joins the file-field list beside `invoices.Invoice`. The coverage test (`backups/test_archive.py`) fails until both are in place, as intended. The section `delivered_documents` comes after `invoices` and `contract_issues`, which its rows point at. A per-ZEV restore gains the overridable conflict `delivered_document_deleted` (a delivered document the backup lacks would be deleted, as for `contract_issue_deleted`), with the new key in `RestoreConflictKind` and in the four locale files.
- **Transfer archive (increment 1b).** `FORMAT_VERSION` 10 → 11 adds the `delivered_documents` section (`delivered_documents.json` and one `delivered_documents/<id>.pdf` per document; it depends on `participants` only), specified in `2026-08-zev-transfer-archive.md`. Documents arrive as they were (delivery time, supersession, withdrawal), with no account reference and no audit event, and the importer checks each file against its `sha256`. Participants and invoices are remapped by archive id and invoice number. The transfer archive carries no `ContractIssue`, so a contract arrives holding its own file: `inbox_document_has_one_body` allows a document with no issue to carry a file (migration `inbox/0002`). Version 10 archives import unchanged and create no rows; a re-imported ZEV re-derives nothing, because delivery is a fact, not a derivation.
- **MCP.** Decided in phase 6b: nothing moves. The MCP endpoint refuses an account that manages or views nothing (403, `2026-09-mcp-server.md` §5), so a participant never reached `find_invoices` or `explain_invoice`, and both stay manager and viewer tools over the live endpoints, which keep serving managers.

### 6.5 Notifications and email

- `invoice.sent` (exists) gains `document_id` in its payload (absent when the invoice could not be delivered into the inbox), so the bell links to `/me/documents` instead of the live invoice list. It is raised after the inbox delivery for that reason, in both `mark_invoice_sent` and `record_email_delivery`. No second event for the same fact.
- New registry type `document.delivered` (audience `participant`, not mandatory) for `contract`, `annual_statement`, `financial_summary`, `tariff_overview`, `credit_note`, `operator`; payload `{ document_id, kind, title }`; `dedupe_key = f"document.delivered:{document.pk}"`.
- The notification is raised by `inbox.views.delivery_response` for the rows a call wrote (`Delivery.fresh`), so every delivering route announces and an idempotent repeat does not. The bell page link is `/me/documents` for both types.
- **Email for non-invoice documents is opt-in per delivery** (`notify`, default off), link-only and without an attachment. It is queued by `delivery_response` through `inbox.emails.queue_document_emails` for the rows the call wrote (`Delivery.fresh`), once the transaction commits, so a repeated idempotent delivery and a refused one send nothing, and an invoice never goes through it (its own email carries the PDF). A participant with no email address is skipped and counted in `without_email`; one without a login is still emailed, the link then leads to sign-in.
- New `EmailTemplate` key `document_delivered`, variables `{participant_name}`, `{zev_name}`, `{title}`, `{inbox_url}` (`build_document_email_context`, field catalogue `admin.emailTemplates.fields.*`). Like the sign-in mail it is sent to one participant of one ZEV, so the shipped default follows the ZEV's `invoice_language` (`DOCUMENT_EMAIL_DEFAULTS_BY_LANGUAGE`, with `DEFAULT_DOCUMENT_EMAIL_SUBJECT` / `_BODY` as the English default in `EMAIL_TEMPLATE_DEFAULTS`); a saved override replaces every language, and an invalid override falls back to the language default. Admins edit it beside the others, in `TRANSLATED_TEMPLATE_KEYS` for the language note.
- Sent by the Celery task `inbox.tasks.send_document_email_task(document_id)` (`max_retries=3`, 60 s apart). It sends nothing for a document that is gone, withdrawn or superseded, or whose participant has lost the address.
- **Traceability is the audit trail, not `EmailLog`.** `EmailLog.invoice` is a required foreign key and the table feeds the readiness view and the invoice detail, so it is left alone. Each send is an `inbox.document.emailed` event (category `participant`, source `celery`, status `SUCCESS`); a send that gave up after its retries is the same action with status `FAILED` and `metadata.error` holding the exception **class** only. The address is never written to the audit event, because an SMTP error text can quote it. Extending `EmailLog` (an optional document link and a migration) is possible later if operators want one log for both.

### 6.6 Backfill

`python manage.py openzev_inbox_backfill [--zev ID] [--dry-run]`, also callable as the Celery task `inbox.tasks.inbox_backfill_task` (logic in `inbox/backfill.py`, `backfill_invoices()` and `backfill_credits()`, each returning a `BackfillReport`; the task answers the combined figures plus the credit notes under `credit_notes`, and the command prints one block per kind). For each invoice matching `sent_to_participant()` with a stored `pdf_file` and no row, it delivers with `delivered_at = sent_at or approved_at or updated_at`; for each credit note with a stored `pdf_file` and no row, with `delivered_at = created_at`. It never renders. Invoices and credit notes with no `pdf_file` (`no_document`; for a credit note this also means its render failed or is still queued, and regenerating the PDF delivers it) or whose file is missing from storage (`file_missing`) are listed in the report and skipped; they remain reachable through the live path until phase 6b, and the **cut-over PR is blocked until both reports are empty or accepted by the operator**. It does not touch contracts (explicit delivery) or reports (never issued before). Idempotent by the unique constraints.

## 7. Frontend

### 7.1 Participant *My documents* page

**Files:** `frontend/src/pages/DocumentsPage.tsx`, `frontend/src/features/inbox/DocumentsList.tsx`, `documentPresentation.ts`, `DocumentsList.css`.

- Route `/me/documents` (participant shell, nav entry *My documents* after *My invoices*, also for a former participant, who reads what it was sent, and for a manager, viewer or admin who holds a participation in any community: the entry sits at the end of the management navigation, the route admits the management shells, and the page keeps only the account's own rows, so what the outbox shows for everyone is not mixed in); *My invoices* (`MyInvoicesPage.tsx`) was kept in phases 1–5 and, since 6b, is the invoice and credit note part of the same inbox query (§7.3).
- Query: `useQuery({ queryKey: queryKeys.inbox.list('mine'), queryFn: listInboxDocuments })`, all pages. A manager who is also a participant gets outbox rows in the same response, so the page keeps only rows whose `participant` is one of the account's own participant ids (`ownParticipantIds`, the rule `personalInvoiceFilter` uses for invoices).
- A list grouped by year (the period's year, else the delivery year; newest first), a kind filter (`FilterTabs` with counts; a kind with no document is left out), a community select shown only when the account has more than one membership. Per row: icon by kind, title, type, delivery date, size, status badge, **Download**. Status is one of *Withdrawn*, *Cancelled* (an invoice whose status is `cancelled`) and *Superseded*, in that order of precedence, from `documentStanding()`. An invoice row is no longer a link (phase 6b): a participant has no live invoice to open, and the PDF carries the details.
- Download fetches the PDF through the API as a blob and saves it under the row's `file_name`; nothing is served from a media URL.
- Container: a page with a list and download actions, no dialogs, per the catalogue in `2026-10-ui-patterns-and-component-catalog.md`. Empty state: "Nothing has been delivered to you yet." Loading and error states as on *My invoices* (`PageSkeleton`, `Notice` with retry).
- Mobile (~400px): single column, download as a full-width row action.
- The *Issued on …* line on the participant *Reports* page moved with phase 6b (§7.3).

### 7.2 Manager outbox and upload

**Files:** `frontend/src/features/inbox/OutboxTab.tsx`, `UploadDocumentDialog.tsx`, `IssueReportsDialog.tsx`, `AudienceFields.tsx`, `DeliveryResultNotice.tsx`, `inbox.css`.

- A *Delivered documents* tab on the billing hub (route `/billing/documents`, `BillingHubPage tab="documents"`, `ZEV_SCOPE`): a table of the selected community's rows (document, participant, delivered date and by whom, status, actions) filtered by participant, kind and year, withdrawn rows included and marked, a *No account yet* badge for a participant with no linked account (joined client-side from the participants list). A manager can answer "did Anna get her statement?" from here. A viewer reads the tab; the actions need `canWriteSelectedCommunity`.
- *Upload document* (dialog, `FormModal` size md; one task, a few fields): title, PDF file (an advisory check of size and type; the server decides), audience (everyone currently in the community / selected participants, chosen from a checkbox list). On success the dialog shows the result: how many received it and how many of them have no account.
- *Issue documents* (dialog): which document (annual statement, financial summary, tariff overview), the year (not for the tariff overview; `YearPicker` over this year and the five before, defaulting to the year just ended), all eligible or selected participants, and a note that issuing again supersedes. The same result view.
- *Withdraw* (row action on an operator document, behind a `ConfirmDialog`).
- *Deliver contract to inbox*: an item in the participant's action menu on the participants page (`ParticipantCardsSection`), never automatic. It posts `{ participant }` to `deliver-contract`, which delivers the participant's latest issued version (§5.3). There is no contract version list in the UI, so naming the participant is what lets the page act without knowing an issue id. An unissued contract answers 404, which the page explains ("download it first").
- **`notify`:** a `NotifyField` checkbox (off by default, "Also notify participants by email", with a hint that the email has a link and no file) in the upload and issue dialogs, and the result view adds `inbox.result.emailed` and `inbox.result.withoutEmail`. The bell notification is not optional. Deliver contract does not offer the checkbox: a single, deliberate action that the participant is told about by the bell; the API accepts `notify` for it.
- All user-facing text in the locale files (`frontend/src/i18n/locales`), a top-level `inbox` block in `de`, `fr`, `it` and `en` (plus `nav.myDocuments` and `pages.billingHub.tabs.documents`).
- **Demo data:** `seed_demo` clears and refills the inbox of both demo communities after the invoice PDFs are written (backfill of the sent invoices, plus a tariff overview and a notice for every current participant with an account of the main community), so the guide screenshots have something to show and a re-seed never lists a document twice.

### 7.3 Participant pages on the inbox (phase 6b)

**Files:** `frontend/src/pages/MyInvoicesPage.tsx`, `frontend/src/features/inbox/InvoiceDocuments.tsx`, `frontend/src/components/dashboard/ParticipantInvoicesCard.tsx`, `frontend/src/features/dashboard/ParticipantDashboardBody.tsx`, `frontend/src/features/reports/ParticipantYearDocuments.tsx`.

- All three read the same query as *My documents* (`queryKeys.inbox.list('mine')`, kept to the account's own participations with `ownParticipantIds`); none calls a live invoice endpoint. `personalInvoiceFilter` is gone.
- **`InvoiceDocumentsTable`** (shared by *My invoices* and the dashboard card): title, community column when the account has several, period, total (with the amount due beneath it when credit was set against the invoice, `InvoiceTotal`), payment state (*due*, *overdue*, *paid* or *cancelled*, `InvoicePaymentState`), the data-review warning when `open_data_impact_count > 0`, and a **Download** button. Up to 640px it is a list of small cards (title and total, period, state, a full-width **Download**) instead of a table that scrolls sideways, as the live-points list does (`InvoiceDocuments.css`). There is no link to a live invoice and no PDF-pending state: a delivered invoice always has its copy. **`CreditNoteDocumentsTable`**: number, the invoice it corrects, date, amount and what is left (both with CHF), status and where it was set off, **Download**; cards on a phone too.
- The empty state of *My invoices* does not say that the operator has issued nothing (an invoice that was sent but has no stored PDF is not delivered, §6.6, and would make that false): it says that invoices delivered to the account appear there.
- *My invoices* shows the invoice rows and, when there are any, the credit note rows below; the empty state and error handling are those of *My documents*. The dashboard card shows the invoice rows only.
- **Annual statement** (`/me/statement`, `ReportsPage`): the two tabs read the newest current *annual statement* and *financial summary* of the selected year from the inbox (`issuedDocumentFor`: own participation, optionally one community, not superseded or withdrawn, `period_start` in that year), show *Issued on …* and the PDF through `downloadInboxDocument`. The year picker offers the years that have a document of either kind (newest shown when the chosen year has none), and the *Tax overview* tab appears only for an account that has a financial summary in any year, because it is for producers. With nothing issued at all the plain five-year list stays and the panel says that the community has not issued the document yet. Nothing is rendered live any more.
- An invoice that was never given a stored PDF cannot be delivered (§6.6), so it does not appear on these pages until the backfill report is cleared; that is what gates the release.
- Deleted with the live reads: the invoice detail link and the participant's live credit note list. `InvoiceDetailPage` is for managers; a participant (an account with no management or viewer access and not an admin, `hasCommunityWideAccess`) whose request for it fails is redirected to *My invoices* instead of seeing an error a retry cannot fix.

### TypeScript types

**File:** `frontend/src/types/api.ts`

```typescript
export type DocumentKind =
  | 'invoice' | 'contract' | 'annual_statement'
  | 'financial_summary' | 'tariff_overview' | 'credit_note' | 'operator'

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
  invoice_figures: InvoiceFigures | null   // 6b
  credit_figures: CreditFigures | null     // 6b
  contract_issue: string | null
}

export interface InvoiceFigures {
  status: string; due_date: string | null
  total_chf: string; credit_applied_chf: string; amount_due_chf: string
  paid_chf: string; outstanding_chf: string; open_data_impact_count: number
}

export interface CreditFigures {
  amount_chf: string; remaining_chf: string; status: CreditStatus
  source_invoice_number: string | null
  applied_to: { invoice_number: string; amount_chf: string }[]
}

export interface DeliveryResult {
  batch_id: string
  delivered: number
  without_account: number
  emailed: number
  without_email: number
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
| Read receipts | **No.** Only `delivered_at`; the outbox shows the delivery date, and a document email, when sent, is in the audit trail (§6.5) | Tracking when a person opened a document is monitoring; "delivered" is enough for a dispute about whether something was sent |
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
| Phase 6 breaks the dashboard card, saved links or the amounts a participant sees | High | Separate release; the backfill report gates it; the invoice link and public page already resolve to the inbox (phase 5); the card, *My invoices* and *Annual statement* are rebuilt on the inbox and its live figures; the MCP tools never served participants. A participant who opens a saved `/billing/invoices/{id}` link lands on *My invoices* |
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
| `test_viewer_reads_but_cannot_write` | a viewer reads the outbox; an upload is refused (404) and delivers nothing |
| `test_manager_of_another_zev_sees_nothing` | 404 |
| `test_admin_sees_all` | |
| `test_anonymous_is_refused` | 401 |
| `test_bad_filters_are_validation_errors` | `kind`, `year`, `participant_id` |
| `test_year_filter_matches_period_or_delivery_year` | |
| `test_download_headers` | attachment, nosniff, no-store, exact bytes |
| `test_contract_download_serves_the_issue_bytes` | reference, no copy |

### Backend — `backups/test_inbox_documents.py` (4) and `zev/test_purge.py` (1), increment 1

`test_rows_and_files_travel_and_contracts_go_by_reference`, `test_another_zev_does_not_carry_the_documents`, `test_restoring_brings_documents_back_with_their_bytes`, `test_a_document_the_restore_would_delete_needs_force`; `test_deletes_delivered_documents_and_their_files_once` (a shared file counts once). Kept out of the shared `build_world` fixture, whose counts other backup tests pin.

### Backend — `inbox/test_api_upload.py` (increment 3, 22 tests)

`UploadTests` (16): a row per current participant sharing one stored file and one batch, `selected` delivers to the chosen only, a participant of another ZEV is a field error, `selected` without participants is a field error, non-PDF magic bytes, oversize (`INBOX_MAX_UPLOAD_BYTES`), empty, the client's content type and filename are ignored, a disabled ZEV refuses a manager but not an admin, a later participant gets no backlog, recipients without an account are counted, the participant downloads exactly what was uploaded (attachment, nosniff, no-store), only a manager of the ZEV may upload (404), anonymous is refused (401), a failed batch leaves no file and no rows, one audit event per recipient. `WithdrawTests` (6): the row and file are kept, the participant loses it while a manager still lists it, withdrawing twice is harmless, a non-operator document is refused (400), a participant, a viewer and a stranger get 404, the withdrawal is audited.

### Backend — `inbox/test_producers.py` (increment 2, 9 tests)

`EmailDeliveryTests`: `test_email_delivery_delivers_attachment_bytes`, `test_stored_bytes_equal_email_attachment`, `test_resent_email_does_not_add_a_row`, `test_a_later_render_does_not_change_the_delivered_file`, `test_a_failed_delivery_does_not_break_recording_the_email`. `MarkSentTests`: `test_mark_sent_delivers_stored_pdf`, `test_mark_sent_renders_missing_pdf`, `test_mark_sent_survives_render_failure`, `test_a_sent_invoice_that_is_cancelled_stays_in_the_inbox_marked_cancelled`.

### Backend — `inbox/test_deliver_contract.py` (increments 2 and 4, 16 tests)

By reference without a copy, the participant can open it, a participant without an account is counted, idempotent (200, `delivered: 0`), an outdated version is refused (409) while the newer one is accepted, the participant and a manager of another ZEV and an unknown id all get 404, a malformed id is 400, a disabled ZEV refuses a manager but not an admin, and an anonymous caller is refused. Issuing a contract on its own delivers nothing. Increment 4 adds delivery by participant: it picks the latest version, a participant with no issued contract and a manager of another ZEV get 404, and exactly one of `contract_issue` and `participant` is required (400).

### Backend — `inbox/test_issue_reports.py` (increment 3, 22 tests)

The statement and summary generators are mocked, so these tests pin who is eligible and what is delivered, not the PDFs (which have their own suites); one test runs the real tariff-overview generator. `AnnualStatementTests` (11): eligibility is sent invoices of the year, the statement is rendered `sent_only`, a cancelled or unsent invoice alone is not eligible, re-issuing supersedes, another year is a separate document, named participants must belong to the ZEV and have something to report, `year` is required and bounded, only a manager may issue, a disabled ZEV refuses a manager, a failing render delivers nothing and leaves no file, recipients without an account are counted. `FinancialSummaryTests` (6): producers only (feed-in, or a credit for local energy), nobody producing is a 400, naming a consumer is refused, re-issuing supersedes, a statement and a summary of one year coexist. `TariffOverviewTests` (5): one shared file for every current participant, re-issuing supersedes per participant and keeps the old bytes, an empty ZEV is refused and leaves no file, only a manager may issue, the real generator renders a PDF.

### Backend — other

- `inbox/test_credit_notes.py` (increment 6a, 16 tests): `DeliveryOnRenderTests` (6) the first render delivers the credit note with its number and issue date, no period, and the exact bytes, a re-render leaves the delivered copy alone, a failed render delivers nothing and a later one does, the participant is told once, a failing delivery neither raises nor undoes the render (and is audited), a credit note with no document is not delivered; `ServiceTests` (4) the number is required, the same number returns the row, another ZEV's identical number is its own document, the database refuses a second row; `BackfillTests` (6) the stored PDF is delivered dated by issue, missing documents are reported, idempotent and `--dry-run` writes nothing, a note delivered by the render is not delivered again, `--zev` limits the run, the command and the task cover credit notes.
- `inbox/test_backfill.py` (increment 2, 8 tests): creates rows for sent invoices dated by `sent_at`, leaves drafts and approved invoices alone, skips and reports missing documents (`no_document`, `file_missing`), `--dry-run` writes nothing, idempotent, the date falls back to approval, `--zev` limits the run, the command prints what it skipped.
- `backups/test_archive.py`: the existing coverage tests pass with the model and file field registered (increment 1).
- `zev/test_transfer_delivered_documents.py` (increment 1b, 20 tests): export / import round trip at format 11 (bytes, history, supersession chain, contract held as a file, invoice link), a v10 archive imports without rows, and rejected archives (checksum, missing member, non-PDF, kind, participant, count) leave no files behind.
- `notifications/test_producers.py` (increment 5, 3 changed or added): `invoice.sent` payload carries `document_id`, names the inbox entry of the invoice, and omits it when the delivery failed.
- `inbox/test_issue_reports.py::AnnouncementTests` (increment 5, 5 tests): an upload notifies participants with a login only, the tariff overview notifies per row, a contract delivered twice notifies once, a refused delivery notifies nobody, a re-issued statement notifies again.
- `inbox/test_document_email.py` (increment 5b, 15 tests): `NotifyFlagTests` (10) nothing is emailed unless asked, every recipient with an address is emailed, a participant without one is counted and skipped, the email links to the inbox with no attachment, the default follows the ZEV's language, a saved template replaces it, a broken template falls back, the tariff overview emails too, a contract delivered twice is emailed once, a refused delivery emails nobody; `SendTaskTests` (5) a send is audited without the address, a withdrawn document is not emailed, an unknown document is ignored, an invoice is never emailed from here, a failing send retries and audits once when it gives up. `invoices/test_field_catalog.py` and `test_template_admin.py` cover the new key.
- `invoices/test_public_invoice_access.py` (increment 5, 3 added): the public PDF serves the delivered snapshot over the current file, serves it when the invoice file is gone, and falls back to the invoice file when the snapshot file is missing.
- `frontend/tests/inbox-notify.test.ts` (increment 5b, 4 tests): `notify` is sent with an upload or an issue only when set, and the result notice reports emails queued and recipients without an address only when there are some.
- `frontend/tests/notifications.test.ts` (increment 5, 2 added): links for `invoice.sent` with and without `document_id`, and for `document.delivered`.
- Phase 6b: `invoices/test_participant_invoice_visibility.py` is rewritten (13 tests) so a participant gets an empty list or 404 on every live endpoint, a former participant too, a manager who rents elsewhere no live access there, and managers are unchanged; the statement and summary tests (`test_reports.py`, `test_disabled_zev_reports.py`, `tests.py`) assert 404 for a participant call. About 35 existing tests that expected participant access were changed to the new answer (`test_access_regression`, `test_access_scoping`, `test_credits`, `test_credit_application`, `test_reading_impact`, `test_payments`, `test_invoice_list_filter`, `test_pdf_approval`, `test_template_admin`, the seed test). `inbox/test_figures.py` (10 tests): what an invoice row carries (total, credit applied, amount due, paid, outstanding), that it is read live while the file's checksum stays, a cancelled invoice owes nothing, open corrections are counted without their evidence, other kinds carry no figures, a credit note's balance and applications, a released application is not listed, the invoice it corrects, the detail route, and a query count that does not grow with the rows.

### Frontend

- `tests/inbox-documents.test.ts` (9): the presentation helpers: the year of a document (period, else delivery), grouping newest year first, the precedence of *withdrawn* over *cancelled* over *superseded*, counts per kind, the advisory upload check (empty, oversize, not a PDF; the server decides), file size formatting, the years offered when issuing.
- `tests/inbox-documents-page.test.ts` (4): the empty state, grouping by year with a superseded badge and only the account's own rows, a cancelled invoice as plain text (no live invoice to open since 6b) with its *Cancelled* badge and a download through the API, the community filter only with more than one membership.
- `tests/participant-invoices-inbox.test.ts` (increment 6b, 15 tests): *My invoices* lists the account's invoices with the total, the amount due beneath it and the payment state and no link to a live invoice, keeps only rows addressed to the account and only invoices in the invoice table, marks an overdue and a cancelled invoice, flags open reading corrections without evidence, lists credit notes with what is left and where they were set off, the empty state, the community column, rows kept with a warning when a later load fails, only the error when the first load fails; and `issuedYears` (2) and `issuedDocumentFor` (the annual document a participant reads: right kind, year, person and community, the newest current one, never a superseded or withdrawn one).
- Changed in 6b: `tests/participant-documents.test.ts` (the *Annual statement* page now reads the issued documents: the same 18 tests on the preview lifecycle, with the issued rows seeded and the abort signal forwarded, plus 3 on what is offered: only years with a document, no tax overview tab without a financial summary, the plain list when nothing was issued), `tests/invoice-detail-participant-redirect.test.ts` (3: a participant lands on *My invoices*, a manager and an admin keep the error), `tests/layout-nav.test.ts` and `tests/route-guard-matrix.test.ts` (*My documents* for a manager or viewer who holds a participation, and the route is open to the management shells), `tests/dashboard-behavior.test.ts` (the invoice card reads the inbox; the polling-for-a-pending-PDF tests are gone, replaced by tests that only the account's rows are listed, that a row shows what is owed and downloads the delivered copy, and that cached rows are kept with a warning), `tests/inbox-documents-page.test.ts` (an invoice row is not a link). The *My invoices* tests in `readiness-cockpit.test.ts` and `invoice-presentation.test.ts` moved to the new file.
- Changed: `tests/billing-hub-order.test.ts` (the third tab) and `tests/layout-nav.test.ts` (*My documents* for a participant; a former participant now keeps two entries, not one).
- `npm run lint`, `npm run lint:style`, `node ../scripts/check-frontend-hex.mjs`, `npm run test:unit`, `npm run build`.
- Screenshots (`08k-delivered-documents`, `08l-my-documents` in the guide set) and a check in a running stack, including a ~400px viewport: neither page overflows horizontally. A `ui-review` pass is still open for the PR review.

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
- [ ] Phase 6b only: a participant gets an empty list or 404 from the live invoice, credit note, annual statement and financial summary endpoints; managers and admins are unchanged; a participant still sees amounts and payment state through the inbox rows.
- [ ] The user guide chapter, `2026-03-invoice-lifecycle-and-communication.md`, `2026-03-community-and-access.md`, `2026-08-zev-transfer-archive.md`, `2026-11-notification-center.md` and the `docs/specs/README.md` index are updated in the phase that changes them.
