# Feature Spec: Audience-specific invoice labels

- Spec ID: SPEC-2026-10-invoice-labels
- Status: Draft
- Scope: Minor
- Type: Change
- Owners: Core maintainers
- Created: 2026-10-17
- Target Release: Phase 8 of the UI patterns rollout
- Related Issues: n/a
- Related ADRs: [0040](../adr/0040-overlay-and-disclosure-pattern-rules.md) (usefulness over decoration), [0037](../adr/0037-issued-invoices-are-corrected-not-deleted.md)
- Related specs: [UI patterns and component catalog](2026-10-ui-patterns-and-component-catalog.md) §10, `2026-03-invoice-lifecycle-and-communication`, `2026-10-payments-and-credits`
- Impacted Areas: frontend, backend (PDF templates), docs

---

This records a decision and the questions it opens. It changes no behaviour
yet and needs its own implementation spec update before work starts.

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

## 3. To decide before implementation

1. **Stored documents.** A stored PDF is a snapshot. Do not regenerate issued
   PDFs silently, and do not imply a stored PDF reflects live payment state.
   Decide which documents get the new rule (new only, or on regeneration) and how
   `ADR 0037` (issued invoices are corrected by credit note) affects a
   *cancelled* marking.
2. **Custom templates.** The invoice PDF template is editable
   (`views_templates.py`, the template editor, the field catalogue). Decide
   whether the status field stays available to custom templates, whether the
   default template changes, and how existing customised templates are treated.
3. **Participant screens.** Which screens show payment status
   (`MyInvoicesPage`, the dashboard cards, the public invoice page) and where the
   current payment data comes from (`2026-10-payments-and-credits`).
4. **Translations and tests.** PDF translations (`pdf_translations.py`), PDF
   tests and the user guide chapter for invoices.

## 4. Out of scope

- Any PDF, template, translation or UI change in the documentation PR that
  introduces this spec.
- The staff interface's status model and the invoice workflow itself.
