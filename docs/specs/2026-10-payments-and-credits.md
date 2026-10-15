# Feature Spec: Payments, credit notes and corrections of paid invoices (#388)

- Spec ID: SPEC-2026-10-payments-and-credits
- Status: Draft
- Scope: Major
- Type: Feature
- Owners: Sebastian Plattner
- Created: 2026-10-15
- Target Release: —
- Related Issues: [#388](https://github.com/splattner/openzev/issues/388), #382 (batch mark-paid and QR-reference matching build on `Payment`), #515 (LEG)
- Related ADRs: 0006 (amended), [0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md)
- Impacted Areas: backend | frontend | docs

---

## 1. Problem and outcome

An invoice can turn out wrong after it has been sent and paid: bad meter readings, a tariff
corrected retroactively, the wrong participant. Today:

- `workflow.cancel_invoice` refuses paid invoices ("Paid invoices cannot be cancelled."). `paid` is
  final (ADR 0006).
- `engine._discard_replaceable_invoices` deletes every overlapping `draft` or `cancelled` invoice on
  regeneration, but `Zev.next_invoice_number()` has already used up its number. The reissued
  invoice leaves an unexplained gap in the number sequence.
- No payment is recorded. `mark_invoice_paid` changes the status and stores no amount or date.
- The aggregations disagree. `financial_summary.py` counts only `PAID` invoices, while
  `annual_statement.py` and `annual_report.py` count every invoice that isn't `CANCELLED`, drafts
  included.

**Outcome:** a paid invoice can be corrected without losing the audit trail, and what the
participant paid moves onto their next invoice:

1. **Payments** record what was received: amount and date, partial payments included.
2. **Credit notes** (Gutschriften) document money owed back. A full reversal cancels the original. A
   partial credit corrects an overcharge and leaves the invoice in place.
3. **Applying credits:** the next invoice deducts open credits after VAT, and a participant who
   leaves can be refunded.
4. **Retention:** an invoice that was ever approved is never deleted by regeneration (ADR 0037).

### 1.1 Changes to #388 since it was written (2026-08-03)

| Issue text | This spec |
|---|---|
| Retention marker `sent_at` | `approved_at`. A PDF can be downloaded once the invoice is approved (`download_pdf` checks no status), and the LEG spec §4.5.2 bases its rule on approval. One field serves both. |
| "Never let an invoice go negative" | Invoices *are* already negative: a producer whose feed-in credit is larger than their consumption gets a negative `total_chf` (`test_engine_vat_producer_credit.py`, `test_engine_edge_cases.py`), and the QR bill then fails to build and is left off. v1 corrects only invoices with `total_chf > 0` (§2, out of scope). |
| Credit copies `vat_rate` | Copies `vat_rate` **and** the source invoice's VAT mode (worked out from its fields, §4.4), because there are now three modes (`not_registered`, `inclusive`, `registered`, ADR 0016) and the invoice has `vat_base_chf` and `embedded_vat_chf` (#957). §4.4 gives the VAT split. |
| `Credit.remaining_chf` stored | Derived from the applications and refunds (§4.4). A stored balance drifts when a draft that consumed credit is deleted by cascade. |
| Permissions open | ZEV managers (`access.can_manage`) record payments and correct invoices. Every correction is audited. |
| #382 as a partner | #382 has shipped (`f687104c`), but it only reordered the batch actions. Batch mark-paid and QR-reference matching still don't exist. The QR bill carries no QRR/SCOR reference, only the invoice number in `additional_information`. Both remain follow-ups. |
| — | New since the issue: the ZEV transfer archive (`zev/transfer/schema.py`), the backup registry (`backups/registry.py`) and the ZEV purge (`zev/purge.py`) have to carry the new tables. |

## 2. Scope

### In scope

| Phase | PR | Area | Details |
|---|---|---|---|
| 0 | this spec | docs | This spec, ADR 0037 |
| 1 | Payments | model | `Payment`. `Invoice.approved_at`. Data migration creating payments for existing paid invoices and filling `approved_at`. |
| 1 | Payments | workflow | `record_payment`, `delete_payment`. `mark_invoice_paid` records one full payment. `cancel_invoice` and invoice deletion refuse invoices that have payments. |
| 1 | Payments | retention | `_discard_replaceable_invoices` and `can_delete_invoice` spare issued invoices |
| 1 | Payments | reports | One aggregation rule, "issued and not cancelled", for the financial summary, annual statement and annual report (§4.6) |
| 1 | Payments | frontend | Record-payment dialog. Payments card on the invoice detail page. "Partly paid" badge. |
| 2 | Credits | model | `Credit`, the credit-note number sequence on `Zev`, the credit-note PDF |
| 2 | Credits | workflow | `correct_invoice` (full reversal / partial credit) |
| 2 | Credits | integration | Transfer archive, backup registry, ZEV purge, participant visibility, audit |
| 2 | Credits | frontend | Correct-invoice dialog. Credits on the invoice detail page and on the participant's invoices page. |
| 3 | Application | model | `CreditApplication`. `Invoice.credit_applied_chf`, `Invoice.amount_due_chf`. Credit refund. |
| 3 | Application | engine | Generation uses up open credits. Regeneration and cancellation give them back. |
| 3 | Application | consumers | QR bill, invoice PDF, email `{total_chf}`/`{amount_due_chf}`, period overview, dashboard, MCP (§4.7) |

### Out of scope

- Correcting invoices with `total_chf <= 0` (net payouts to producers). `correct_invoice` refuses
  them with a clear error, and payments on them are kept as they are today (§4.2). This needs
  negative credits, i.e. a balance the participant owes, which then raise the next invoice. Every
  credit rule would have to handle both signs.
- Goodwill or deposit credits without a source invoice. `Credit.source_invoice` is nullable so they
  can come later.
- Emailing a credit note on its own. In v1 it can be downloaded, appears in the participant portal,
  and is referenced on the invoice that uses it.
- Overpayment. `record_payment` refuses more than the outstanding amount. A follow-up could turn an
  overpayment into a credit.
- Bank-statement import, QRR/SCOR reference on the QR bill, batch mark-paid (#382 follow-ups).
- Filing VAT corrections automatically with the ESTV.
- Deleting a participant who has issued invoices. Today the cascade from `Participant` removes all
  of their invoices, issued ones included. That is a pre-existing retention gap with its own issue.
- LEG documents. The LEG spec reuses `approved_at` and, later, `Credit` instead of
  `LegExternalSettlement`.

## 3. Actors, permissions, and ZEV scope

| Actor | Payments | Correct (`correct`) | Credits | Refund |
|---|---|---|---|---|
| `admin` | read, record, delete | yes | read, PDF | yes |
| manager (`access.can_manage`) | read, record, delete | yes | read, PDF | yes |
| viewer (`access.can_view`) | read | no (404 via the write-scoped queryset) | read, PDF | no |
| `participant` | no (invoice shows `paid_chf` / `outstanding_chf` only) | no | read own, PDF | no |

The action endpoints use `IsAuthenticated, HasZevAccess` and resolve the invoice through the
existing write-scoped `InvoiceViewSet` queryset, like `mark-paid`. A disabled ZEV refuses the write
actions for non-admins through `_deny_if_zev_disabled`. `CreditViewSet` scopes its queryset the way
`InvoiceViewSet.get_queryset` does, and a participant sees only their own credits. Credits are
visible to the participant from creation, because a credit note is issued the moment it exists.

## 4. Data model and rules

### 4.1 `Invoice` additions

| Field | Phase | Type | Default | Notes |
|---|---|---|---|---|
| `approved_at` | 1 | `DateTimeField(null=True, blank=True)` | `None` | Stamped by `approve_invoice` and by the batch approval. Never cleared. Read-only in the serializer. |
| `credit_applied_chf` | 3 | `DecimalField(10, 2)` | `0` | Sum of the invoice's active `CreditApplication` rows |
| `amount_due_chf` | 3 | `DecimalField(10, 2)` | `0` | `max(total_chf - credit_applied_chf, 0)` when `total_chf > 0`, otherwise `total_chf`. The engine sets it. Migration: `= total_chf`. |

Serializer additions: `approved_at`, `paid_chf` (sum of payments), `outstanding_chf` (amount due
minus `paid_chf`. Before phase 3 the amount due is `total_chf`), and, on the detail serializer, a
nested `payments` list. Phase 2 adds `credits` (credit notes whose source is this invoice). Phase 3
adds `credit_applied_chf`, `amount_due_chf` and `credit_applications`. In the list serializer,
`paid_chf` comes from a `Sum` annotation so the list query count doesn't grow.

**Issued:** `approved_at IS NOT NULL`. A helper `issued()` returning a `models.Q`, next to
`sent_to_participant()` in `invoices/models.py`.

### 4.2 `Payment` (phase 1)

**Model:** `invoices.models.Payment`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` pk | `uuid4` | |
| `invoice` | `ForeignKey(Invoice, CASCADE, related_name="payments")` | — | CASCADE so the ZEV purge and an admin delete of a never-issued invoice still work. The API refuses to delete an invoice that has payments (§4.5). |
| `amount_chf` | `DecimalField(10, 2)` | — | Not zero. Same sign as the invoice's amount due. |
| `paid_on` | `DateField` | today (Swiss civil date) | Not in the future |
| `note` | `CharField(500, blank=True)` | `""` | e.g. a bank reference |
| `source` | `CharField(20)`, choices `manual` \| `mark_paid` \| `backfill` | `manual` | How the row was created |
| `created_by` | `ForeignKey(User, SET_NULL, null=True)` | — | |
| `created_at` | `DateTimeField(auto_now_add=True)` | — | |

Ordering `["paid_on", "created_at", "id"]`. Check constraint `amount_chf <> 0`.

**`record_payment(invoice, *, amount_chf, paid_on, note="", user) -> Payment`** in
`invoices/workflow.py`. It runs under the same row lock as `_lock_and_transition`:

- The invoice must be `sent` or `paid`. The error messages are "Only sent invoices can receive
  payments." and "Invoice is already fully paid." An approved invoice has to be marked sent first.
  That keeps today's order (`sent → paid`) and avoids a new `approved → paid` transition.
- `amount_chf` must not be zero and must have the sign of the amount due. When the amount due is
  positive, `paid_chf + amount_chf` must not exceed it ("Payment exceeds the outstanding amount of
  CHF {x}."). When the amount due is zero or negative (a producer payout), only one payment equal to
  the amount due is accepted. That is the `mark-paid` path, and it keeps today's behaviour for
  payouts.
- When `paid_chf` then equals the amount due, the status moves `sent → paid`. Otherwise it stays
  `sent`, and "partly paid" is shown from `paid_chf > 0`. There is no new status.

**`mark_invoice_paid(invoice, *, paid_on=None, user=None)`** keeps its endpoint and its result. It
calls `record_payment` for the outstanding amount with `source="mark_paid"`. An invoice with an
amount due of zero moves to `paid` without a payment row.

**`delete_payment(payment, *, user)`** corrects a payment entered by mistake. It is refused when the
invoice is `cancelled`, and from phase 2 also when a credit was derived from the invoice. When the
invoice was `paid` and the sum now falls short of the amount due, the status moves back
`paid → sent`. That is a new transition, reachable only here.

**Backfill (data migration):** every invoice with `status = paid` gets one `Payment` with
`amount_chf = total_chf` and `source = backfill`. `paid_on` is the date of the newest `AuditEvent`
with `action_type = "invoice.mark_paid"` and `target_id = invoice.pk`, falling back to the civil
date of `updated_at`. Invoices with a total of zero get no payment.

### 4.3 `approved_at` (phase 1)

- Stamped with `timezone.now()` in `approve_invoice` (`extra_fields`) and in `approve_all`. Open PR
  #1022 routes batch approval through the locked workflow. Whichever lands second makes sure both
  paths stamp the field.
- Backfill: for `status in (approved, sent, paid)`, use the newest `invoice.approve` audit event,
  else `sent_at`, else `updated_at`. For `cancelled` with `sent_at` set, use `sent_at`, because the
  invoice provably went out. Other cancelled invoices keep `NULL`. Whether they were approved before
  cancellation can only be guessed from audit events, and they behave as they do today.
- Transfer archive: added to `INVOICE_FIELDS` as an optional field (older archives import with
  `NULL`). Backup: covered by the `Invoice` model dump.

### 4.4 `Credit` (phase 2)

**Model:** `invoices.models.Credit`

| Field | Type | Default | Constraints / Notes |
|---|---|---|---|
| `id` | `UUIDField` pk | `uuid4` | |
| `credit_number` | `CharField(50)` | — | `UniqueConstraint(zev, credit_number)` |
| `zev` | `ForeignKey(Zev, PROTECT, related_name="credits")` | — | Deleted explicitly by `zev/purge.py` before invoices, like `Invoice` |
| `participant` | `ForeignKey(Participant, CASCADE, related_name="credits")` | — | Same as `Invoice.participant` |
| `kind` | `CharField(20)`, choices `reversal` \| `adjustment` | — | Full reversal or partial credit |
| `source_invoice` | `ForeignKey(Invoice, PROTECT, null=True, related_name="credits")` | — | Required in v1. Nullable for later goodwill credits. |
| `reason` | `TextField` | — | Required, printed on the credit note |
| `amount_chf` | `DecimalField(10, 2)` | — | Gross, `> 0` (check constraint) |
| `vat_mode` | `CharField(20)` | — | The source invoice's VAT mode. `Invoice` doesn't store it, so it is worked out from the invoice: `embedded_vat_chf` set → `inclusive`, `vat_base_chf` set or `vat_chf ≠ 0` → `registered`, otherwise `not_registered`. Not `Zev.vat_mode`, which may have changed since. |
| `vat_rate` | `DecimalField(5, 4)` | — | Copied from `source_invoice.vat_rate` |
| `vat_chf` | `DecimalField(10, 2)` | `0` | VAT contained in `amount_chf`, see below |
| `embedded_vat_chf` | `DecimalField(10, 2, null=True)` | — | For `inclusive` only |
| `refunded_chf` | `DecimalField(10, 2)` | `0` | Phase 3 |
| `refunded_on` | `DateField(null=True)` | — | Phase 3 |
| `pdf_file`, `pdf_status` | as on `Invoice` | | Same render pipeline and status semantics as `InvoicePdfStatus` |
| `issuer`, `recipient` | `JSONField` | | Copied from `source_invoice` (frozen since approval, #761) |
| `created_by` | `ForeignKey(User, SET_NULL, null=True)` | | |
| `created_at` | `DateTimeField(auto_now_add=True)` | | |

**Number sequence:** new `Zev.credit_note_prefix` (`CharField(10)`, default `"CN"`) and
`Zev.credit_note_counter` (`PositiveIntegerField`, default `1`). `Zev.next_credit_note_number()`
uses the same locked allocator as invoice numbers (open PR #1021). Both fields go into the ZEV
settings serializer and the transfer archive (the counter is pushed past the imported credits, the
same way `invoice_counter` is in `zev/transfer/importer.py`).

**VAT split:**
- *Reversal* where `amount_chf == source.total_chf`: `vat_chf = source.vat_chf` and
  `embedded_vat_chf = source.embedded_vat_chf`, copied exactly.
- *Reversal of an underpaid invoice*, or an *adjustment*: `registered` takes
  `vat_chf = round(amount_chf × vat_rate / (1 + vat_rate), 2)`. `inclusive` takes the same formula
  into `embedded_vat_chf`, with `vat_chf = 0`. `not_registered` takes `0`.

**Derived balance:** `remaining_chf = amount_chf - Σ active applications - refunded_chf`, exposed as
a queryset annotation and a serializer field. A derived status is shown in the UI: `open`
(remaining > 0), `used` (remaining = 0 and no refund), `refunded` (`refunded_chf > 0` and
remaining = 0).

**`correct_invoice(invoice, *, kind, reason, amount_chf=None, user) -> Credit`** in
`invoices/workflow.py`. It locks the invoice row and, in one transaction:

1. Guards. The invoice is `paid`, or `sent` with `paid_chf > 0`. A `sent` invoice with no payments
   is simply cancelled. `total_chf > 0`. `reason` is not blank.
2. `kind = reversal`: the credit amount is `paid_chf`, i.e. what was received, not `total_chf`. The
   status moves to `cancelled`. This is the only way out of `paid`, and the only cancellation of an
   invoice with payments.
3. `kind = adjustment`: `amount_chf` is required, and `0 < amount_chf ≤ paid_chf - Σ existing credits
   on the invoice`. The invoice keeps its status and amounts.
4. Allocates the credit number, creates the `Credit`, and queues the PDF render on commit.
5. Records the audit event `invoice.correct` (§5.3).

Once a reversal has cancelled the invoice, the period can be regenerated as usual. The cancelled
original is kept (§4.5).

### 4.5 Retention and deletion (phase 1)

| Situation | Today | New |
|---|---|---|
| Regeneration finds a `draft`, never approved | deleted | deleted |
| Regeneration finds `cancelled` with `approved_at IS NULL` | deleted | deleted |
| Regeneration finds `cancelled` with `approved_at` set | deleted | **kept**. The new invoice is created next to it. |
| Regeneration finds `approved`/`sent`/`paid` | blocked (409) | blocked (unchanged, `locked_overlapping_invoices`) |
| Non-admin `DELETE` | draft or cancelled | draft or cancelled **and** `approved_at IS NULL` |
| Admin `DELETE` | any | any invoice **without payments**, and from phase 2 without credits. An admin can still remove an issued invoice that never received money. |
| `cancel` with payments | — | refused: "Invoices with recorded payments are corrected, not cancelled." |

`_discard_replaceable_invoices` filters on
`status__in=[DRAFT, CANCELLED], approved_at__isnull=True`. `can_delete_invoice` gains the same
condition. ADR 0006's "regeneration may replace only draft/cancelled invoices" becomes "only never
issued draft/cancelled invoices".

**Several invoices for one participant/period.** These queries are checked against kept cancelled
invoices:

- `period_overview.compute_period_overview`: newest invoice first (`-created_at`). The replacement is
  newer than the cancelled original, so it wins. When no replacement exists yet, the cancelled
  original is shown with its generation eligibility, as today. **No change needed.** A test pins it.
- `readiness._bulk_invoice_steps` / `_load_bulk`: ordered `participant_id, -created_at`, and
  cancelled rows are skipped in the counts. **No change needed.** A test pins it.
- `readiness.resolve_cockpit_period` (`status == CANCELLED: continue`) and `_covered_participant_ids`: skip
  cancelled already.
- `financial_summary` overlap deduplication ("newest wins"): it must ignore cancelled invoices
  before deduplicating. This falls out of §4.6.
- `mcp_server/tools/explain_invoice.py` already skips `cancelled` rows when it looks for the
  previous invoice.

### 4.6 One aggregation rule (phase 1)

A new helper `billed_invoices(zev, participant, start, end)` in `invoices/models.py` returns the
invoices that are issued, not `cancelled`, and inside the window. It is used by:

| Report | Today | New |
|---|---|---|
| `financial_summary.generate_financial_summary_pdf` | `status = paid` | `billed_invoices`. The paid amount is shown from `Payment` per invoice. |
| `annual_statement` invoice table and totals | everything except `cancelled` (drafts included) | `billed_invoices` (the `sent_only` filter for participants stays) |
| `annual_report` | everything except `cancelled` | `billed_invoices` |
| `views_dashboard` `total_revenue` | `sent` + `paid` | unchanged in phase 1. Phase 3: `billed_invoices` minus adjustment credits. |

From phase 2, adjustment credits (`kind = adjustment`) inside the window are listed as negative rows
in the annual statement's invoice table and subtracted from its totals. Reversal credits are not,
because their source invoice is already excluded as cancelled. kWh figures in the annual statement
come from readings, not invoices, so a correction caused by readings changes them when the readings
change. That is intended and is noted in the user guide.

### 4.7 `CreditApplication` and `amount_due_chf` (phase 3)

**Model:** `invoices.models.CreditApplication`

| Field | Type | Notes |
|---|---|---|
| `id` | `UUIDField` pk | |
| `credit` | `ForeignKey(Credit, PROTECT, related_name="applications")` | |
| `invoice` | `ForeignKey(Invoice, CASCADE, related_name="credit_applications")` | CASCADE: deleting a never-issued draft gives the credit back automatically |
| `amount_chf` | `DecimalField(10, 2)` | `> 0` |
| `released_at` | `DateTimeField(null=True)` | Set when an issued invoice using the credit is cancelled. A released application no longer counts. |
| `created_at` | `DateTimeField(auto_now_add=True)` | |

**Engine:** after totals and VAT, when `total_chf > 0`, `generate_invoice` locks the participant's
open credits (`select_for_update`, oldest first) and creates applications until `total_chf` is
covered or the credits run out. Then `credit_applied_chf = Σ` and
`amount_due_chf = total_chf - credit_applied_chf`. Line items, `subtotal_chf`, `vat_chf` and
`total_chf` are untouched, so tariff grouping and the allocation reconciliation tests keep holding.
When `total_chf <= 0`, no credit is applied.

**Release:** `cancel_invoice` and the reversal in `correct_invoice` set `released_at` on the
invoice's active applications. Regeneration deletes drafts, and the cascade removes their
applications.

**Refund:** `refund_credit(credit, *, refunded_on, note, user)` books the whole remaining amount as
paid out (`refunded_chf += remaining`). Audit event `credit.refund`.

**Consumers of `total_chf` → decision:**

| Consumer | Uses |
|---|---|
| QR bill amount (`pdf._build_qr_svg`) | `amount_due_chf`. No slip when it is 0 (as today for ≤ 0). |
| Invoice PDF totals block | `total_chf`, then the lines "Credit CN-… applied" and "Amount due" |
| Email variables (`email_context`, `Zev` email template help text) | `{total_chf}` unchanged, new `{amount_due_chf}`. The default template switches to `{amount_due_chf}`. |
| `outstanding_chf`, `record_payment` limit | `amount_due_chf` |
| Period overview, batch toolbar, `InvoicePeriodRowsTable` | Shows `amount_due_chf` when it differs from `total_chf` |
| `views_dashboard` revenue | `total_chf` of billed invoices minus adjustment credits |
| Annual statement / report / financial summary | `total_chf` (the value billed). Credits listed separately (§4.6). |
| MCP `find_invoices` / `explain_invoice` | Adds `amount_due_chf`, `paid_chf`, and credits |
| `field_catalog_data` (template field catalogue) | Adds `amount_due_chf`, `credit_applied_chf`, `paid_chf` |

## 5. API contracts

All paths are under `/api/v1/invoices/`.

### 5.1 Payments (phase 1)

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `invoices/{id}/payments/` | GET | `IsAuthenticated, HasZevAccess` (viewer and up) | Payments of the invoice |
| `invoices/{id}/payments/` | POST | `IsAuthenticated, HasZevAccess`, manager | Body `{amount_chf, paid_on?, note?}` → `201` with the updated `Invoice` (detail shape). Guard failures → `400 {"error": …}`. |
| `invoices/{id}/payments/{payment_id}/` | DELETE | as POST | → `200` with the updated `Invoice`. `400` when the guard refuses. |
| `invoices/{id}/mark-paid/` | POST | unchanged | Optional body `{paid_on}`. Records the outstanding amount. Response unchanged. |
| `invoices/{id}/cancel/` | POST | unchanged | New `400` when payments exist |
| `invoices/{id}/` | DELETE | unchanged | New `400` when payments exist or (non-admin) the invoice was issued |

**`PaymentSerializer`** — fields `id, invoice, amount_chf, paid_on, note, source, created_by_name,
created_at` (read-only: everything except `amount_chf, paid_on, note`).

### 5.2 Corrections and credits (phase 2/3)

| Endpoint | Method | Permission | Behaviour |
|---|---|---|---|
| `invoices/{id}/correct/` | POST | `IsAuthenticated, HasZevAccess`, manager | Body `{kind: "reversal" \| "adjustment", reason, amount_chf?}` → `201 {"invoice": Invoice, "credit": Credit}`. `400` on a guard failure. |
| `credits/` | GET | `IsAuthenticated` (scoped queryset) | Filters `zev_id`, `participant_id`, `status` (`open`, `used`, `refunded`) |
| `credits/{id}/` | GET | as list | |
| `credits/{id}/pdf/` | GET | as list | Like `invoices/{id}/pdf/`, `404` before the render |
| `credits/{id}/generate-pdf/` | POST | manager | Re-render |
| `credits/{id}/refund/` | POST | manager | Phase 3. Body `{refunded_on, note?}` → `200 Credit`. `400` when nothing remains. |

**`CreditSerializer`** — fields `id, credit_number, zev, participant, participant_name, kind,
source_invoice, source_invoice_number, reason, amount_chf, vat_mode, vat_rate, vat_chf,
embedded_vat_chf, remaining_chf, refunded_chf, refunded_on, status, pdf_url, pdf_status,
created_by_name, created_at`. All read-only.

### 5.3 Audit events

| `action_type` | Target | Changes / metadata |
|---|---|---|
| `invoice.payment_record` | `invoices.Invoice` | `{"status": before/after}`, metadata `{amount_chf, paid_on, payment_id}` |
| `invoice.payment_delete` | `invoices.Invoice` | same |
| `invoice.mark_paid` | unchanged | metadata adds `{amount_chf, payment_id}` |
| `invoice.correct` | `invoices.Invoice` | `{"status": …}`, metadata `{kind, credit_id, credit_number, amount_chf, reason}` |
| `credit.refund` | `invoices.Credit` | metadata `{amount_chf, refunded_on}` |

Denied attempts are recorded with `AuditEventStatus.DENIED`, the same way
`_perform_status_transition` does it.

## 6. Async and integration behavior

- **Credit-note PDF:** rendered the same way as invoices (`pdf_status` pending → ready/failed,
  conditional update when the file is stored). Template `templates/invoices/credit_note_pdf.html`
  on the shared PDF design base (SPEC-2026-08-contract-pdf-redesign), admin-editable like the other
  `PdfTemplate`s. The content: issuer, recipient, credit number and date, "Credit note for invoice
  INV-… dated …", the reason, the amount with the VAT breakdown for the source's VAT mode, and a
  note that the amount is set against the next invoice or refunded. There is no QR bill.
- **Transfer archive:** new sections `payments`, `credits`, `credit_applications`, plus
  `Zev.credit_note_prefix` and `credit_note_counter`. The credit PDF bytes go into the same optional
  PDF section as invoice PDFs. Older archives import without these sections.
- **Backups:** `ZevPart("invoices.Payment", "invoice__zev")`, `ZevPart("invoices.Credit", "zev")`,
  `ZevPart("invoices.CreditApplication", "credit__zev")`, and a `MEDIA_FIELDS` entry for
  `Credit.pdf_file`.
- **ZEV purge:** deletes `CreditApplication`, then `Credit`, then invoices (whose cascade removes
  payments).
- **Seed demo:** one partly paid invoice, one reversal with its regenerated replacement, one
  adjustment credit applied to the following period.

## 7. Frontend

Container choices follow the UI patterns spec from open PR #1015 if it has landed, otherwise
SPEC-2026-04. All text goes through i18n (de, fr, it, en).

### 7.1 Phase 1

- **`frontend/src/features/invoices/RecordPaymentModal.tsx`** (new): amount (defaults to
  `outstanding_chf`), date (defaults to today), note. Opened by the existing "Mark paid" action in
  `useInvoiceActions.tsx`, which keeps one-click mark-paid as the dialog's primary button with the
  full amount.
- **`InvoiceDetailPage.tsx`**: a "Payments" card listing payments (date, amount, note, who), a
  delete action per row for managers, and `paid_chf` / `outstanding_chf`.
- **Status badge** (`invoiceStatus.ts`): `sent` with `paid_chf > 0` shows "Partly paid".
- API client (`lib/api/invoices.ts`): `listPayments(invoiceId)`, `recordPayment(invoiceId, body)`,
  `deletePayment(invoiceId, paymentId)`. `markInvoicePaid(invoiceId, paidOn?)`.
- Query invalidation: invoice detail, invoice list, period overview, readiness.

```typescript
export interface Payment {
    id: string
    invoice: string
    amount_chf: string
    paid_on: string
    note: string
    source: 'manual' | 'mark_paid' | 'backfill'
    created_by_name: string | null
    created_at: string
}
// Invoice gains:
//   approved_at?: string | null
//   paid_chf?: string
//   outstanding_chf?: string
//   payments?: Payment[]            // detail only
```

### 7.2 Phase 2

- **`frontend/src/features/invoices/CorrectInvoiceModal.tsx`** (new): choose full reversal or
  partial credit, reason (required), amount (partial only, capped). It explains what happens: the
  invoice is cancelled, a credit note over CHF x is issued, and the period can be regenerated. The
  action appears on `paid` invoices and on `sent` invoices with payments.
- **`InvoiceDetailPage.tsx`**: a "Credit notes" card (number, kind, amount, remaining, PDF). A
  cancelled original links to its credit note and the replacement.
- **`MyInvoicesPage.tsx`**: the participant's credit notes with PDF download.
- `Credit` type and `listCredits`, `getCredit`, `correctInvoice`, `downloadCreditPdf`.

### 7.3 Phase 3

- Invoice totals in `InvoicePresentation.tsx`, `InvoicePeriodRowsTable.tsx`, `MyInvoicesPage.tsx`,
  `PublicInvoicePage.tsx` and `ParticipantInvoicesCard.tsx` show "Amount due" when it differs from
  the total.
- Refund action on an open credit, for managers.
- `Invoice` gains `credit_applied_chf`, `amount_due_chf`, `credit_applications`.

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A consumer keeps reading `total_chf` as the amount owed | High | The §4.7 table. The QR bill and `outstanding_chf` switch in the same PR as `amount_due_chf`. Tests on the QR amount. |
| Backfilled `paid_on` is imprecise | Low | Taken from the audit event where one exists. `source = backfill` marks it. |
| Two drafts for one participant use up the same credit | Medium | Credits are locked with `select_for_update` during generation. The balance is derived, not stored. |
| Retained cancelled invoices confuse the period views | Medium | Ordering checked (§4.5) and pinned by tests |
| VAT on a credit for a VAT-registered ZEV that has already filed the quarter | Medium | The credit note carries the original `vat_rate` and VAT amount. The user guide explains booking it in the current period. No automation. |
| Correcting payouts (`total_chf <= 0`) is still impossible | Medium | Refused with a clear error. Out of scope, named in ADR 0037. |
| Deleting a participant still cascades their issued invoices | Medium | Pre-existing. Separate issue (§2). |
| Overlap with open PRs #1021 (numbering) and #1022 (approval) | Low | Phase 1 rebases on whichever has merged. The credit sequence reuses #1021's allocator. |

## 9. Test plan

Test names are the intended set. Counts are filled in when each phase lands.

### Phase 1 — `invoices/test_payments.py` (new), `invoices/test_workflow.py`

| Test | Asserts |
|---|---|
| `test_record_partial_payment_keeps_invoice_sent` | `paid_chf` = amount, status `sent` |
| `test_payments_covering_total_mark_invoice_paid` | Second payment moves it to `paid` |
| `test_payment_above_outstanding_is_refused` | `400`, no row |
| `test_payment_on_approved_or_draft_is_refused` | Guard |
| `test_mark_paid_records_full_payment` | One `mark_paid` payment equal to the outstanding amount |
| `test_mark_paid_on_payout_invoice_records_negative_payment` | `total_chf < 0` keeps working |
| `test_mark_paid_zero_total_has_no_payment` | Status `paid`, no row |
| `test_delete_payment_reverts_paid_to_sent` | New transition |
| `test_cancel_refuses_invoice_with_payments` | `400` |
| `test_viewer_cannot_record_payment` / `test_participant_cannot_list_payments` | Scope |
| `test_disabled_zev_refuses_payment_for_non_admin` | `_deny_if_zev_disabled` |
| `test_payment_audit_events` | `invoice.payment_record` / `payment_delete` |
| `test_approve_stamps_approved_at` / `test_approve_all_stamps_approved_at` | Both paths |
| `test_regeneration_keeps_issued_cancelled_invoice` | Retained, new draft next to it |
| `test_regeneration_deletes_never_issued_cancelled_invoice` | Unchanged behaviour |
| `test_owner_cannot_delete_issued_cancelled_invoice` / `test_admin_cannot_delete_invoice_with_payments` | Deletion rules |
| `test_period_overview_prefers_replacement_over_cancelled_original` | §4.5 |
| `test_readiness_ignores_retained_cancelled_invoice` | §4.5 |
| `test_backfill_creates_payment_per_paid_invoice` / `test_backfill_sets_approved_at` | Migration (migrator test) |
| `test_reports_use_billed_invoices` (annual statement, annual report, financial summary) | Drafts excluded, cancelled excluded, issued included |
| `test_transfer_roundtrip_keeps_payments_and_approved_at` | Archive |

### Phase 2 — `invoices/test_credits.py` (new)

Reversal of a paid invoice (status, credit = `paid_chf`, number from its own sequence), reversal of
an underpaid invoice (credit = paid, VAT scaled), adjustment within the cap and above it, refusal on
`total_chf <= 0`, refusal on a `sent` invoice without payments, the VAT split for each `vat_mode`,
`delete_payment` refused once a credit exists, regeneration after a reversal, credit PDF render and
download, participant visibility, transfer/backup/purge round-trips, audit events, annual statement
with an adjustment credit.

### Phase 3 — `invoices/test_credit_application.py` (new)

The engine applies credit after VAT (line items unchanged), floors at zero and carries the
remainder, several credits oldest first, no application when `total_chf <= 0`, regeneration
releases (cascade), cancellation releases (`released_at`), refund, QR bill amount = `amount_due_chf`
and no slip at 0, concurrent generation doesn't double-use a credit (PostgreSQL leg), email
variable `{amount_due_chf}`.

### Frontend

`npm run lint`, `lint:style`, hex check, `test:unit` (status badge "partly paid", amount-due
rendering), `build`. Screenshots of the payment and correction dialogs at desktop and ~400px width.

### Acceptance criteria

- [ ] A partly paid invoice shows what was received and what is outstanding. Mark-paid still works
      in one click.
- [ ] No invoice that was ever approved is deleted by regeneration or by a non-admin.
- [ ] A paid invoice can be reversed. The original stays as cancelled with its number, a credit note
      PDF references it, and the period can be regenerated.
- [ ] An overcharge can be credited partially without cancelling the invoice.
- [ ] The next invoice deducts the credit after VAT. The QR bill asks for the amount due, never less
      than zero. The remainder is carried forward.
- [ ] A remaining credit can be marked as refunded.
- [ ] The financial summary, annual statement and annual report agree on which invoices count.
- [ ] Payments, credits and applications survive the transfer archive and a backup/restore.
