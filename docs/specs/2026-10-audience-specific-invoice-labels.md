# Feature Spec: Audience-specific invoice labels

- Spec ID: SPEC-2026-10-invoice-labels
- Status: Implemented
- Scope: Minor
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-17
- Target Release: Phase 8 of the UI patterns rollout
- Related Issues: [#1069](https://github.com/splattner/openzev/issues/1069)
- Related ADRs: [0040](../adr/0040-overlay-and-disclosure-pattern-rules.md) (usefulness over decoration), [0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md)
- Related specs: [UI patterns and component catalog](2026-10-ui-patterns-and-component-catalog.md) §10, `2026-03-invoice-lifecycle-and-communication`, `2026-10-payments-and-credits`
- Impacted Areas: frontend, backend (PDF templates), docs

---

This records a decision, the answers to the questions it opened (§3) and how it
was implemented (§5).

## 1. Problem and outcome

An invoice's workflow status means different things to different readers. The
staff who manage invoices need to know whether one is approved or sent. The
recipient needs to know what to pay and by when. Today the same status text is
shown to everyone: the default invoice PDF prints
`{{ tr.status }}: {{ status_display }}` unconditionally
(`backend/templates/invoices/invoice_pdf.html`, `.document-status`), so an
ordinary issued invoice carries an internal status that tells its recipient
nothing.

The outcome: each audience sees the information that helps it.

## 2. Decision

| Audience / surface | Decision |
|---|---|
| Staff management interface | The internal Draft / Approved / Sent / Paid distinctions stay, presented quietly (neutral treatment, not a coloured capsule on every row). |
| Participant-facing screens | Emphasise payment information: Payment due, Overdue, Paid, from reliable current data. |
| Ordinary issued invoice document | No status label. Internal approval and delivery states belong in the staff UI; current payment state belongs on the participant screen. |
| Draft or cancelled document | A prominent, plain **Draft** or **Cancelled** marking, enough to say how the document must be read. |

## 3. Decisions

1. **Stored documents: new renders only.** The new rule applies to every PDF
   rendered from now on, whether first generated or regenerated for any other
   reason. Issued PDFs already stored are never regenerated silently and keep
   their old `Status:` line. A cancelled invoice carries the **Cancelled**
   marking when its PDF is next rendered; a credit-note reversal (ADR 0037) does
   not touch the original's stored PDF, which stays as issued.
2. **Custom templates: the field stays, only the default changes.**
   `status_display` and `invoice.get_status_display` stay in the context and the
   field catalogue, so existing customised templates render exactly as before.
   The on-disk default template drops the status line and prints
   `document_marking`. The catalogue gains `document_marking.label` and
   `document_marking.kind`; the `tr.status` entry goes because the default
   template no longer uses it (a custom template can still write
   `{{ tr.status }}`). Customised templates in the database are not rewritten.
3. **Participant screens: derived from data already served.** My invoices, the
   dashboard invoices card, the invoice detail page for a participant and the
   public invoice page show **Payment due**, **Overdue**, **Paid** (and
   **Cancelled** for a cancelled invoice). The state is derived in
   `paymentState` (`features/invoices/invoiceStatus.ts`) from `status`,
   `due_date` (compared with today's Swiss civil date), the amount due and
   `outstanding_chf` from `2026-10-payments-and-credits`: paid when the status is
   `paid` or payments cover the amount due, overdue when the due date has passed,
   otherwise due. Nothing is shown for a payout or a zero amount. The public
   invoice payload gains `due_date`. Overdue is issue text (a concrete problem);
   the other states are plain text, nothing green (UI patterns §10.1).
4. **Staff screens.** Draft / Approved / Sent / Paid / Cancelled (and Partly
   paid) stay, as one neutral `.badge-tag` (`INVOICE_STATUS_BADGE_CLASS`)
   instead of a coloured capsule per row.
5. **Translations and tests.** `pdf_translations.py` gains `marking_draft` and
   `marking_cancelled` (de, fr, it, en); frontend `invoice.payment.*` and
   renamed participant column headers (**Payment**). Tests:
   `StatusTranslationTests` (PDF), `test_public_invoice_access`, and
   `frontend/tests/payment-state.test.ts`.

## 4. Out of scope

- Any PDF, template, translation or UI change in the documentation PR that
  introduces this spec.
- The staff interface's status model and the invoice workflow itself.

## 5. Implementation

| Area | Change |
|---|---|
| `backend/invoices/pdf.py` | `_document_marking` and the `document_marking` context key |
| `backend/templates/invoices/invoice_pdf.html` | `.document-status` line replaced by `.document-marking` (draft / cancelled only) |
| `backend/invoices/pdf_translations.py`, `template_context.py`, `field_catalog_data.py` | Marking labels, sample context, catalogue entries |
| `backend/invoices/views_public.py` | `due_date` in the public payload |
| Frontend | `InvoicePaymentState` (participant screens), neutral `InvoiceStatusBadge` (staff), `PublicInvoicePage` payment label, `invoice.payment.*` i18n |
