# ADR 0037: Issued invoices are corrected by credit note, never deleted

- Status: Proposed
- Date: 2026-10-15
- Amends: ADR 0006

## Context

ADR 0006 made `paid` final and let regeneration replace any `draft` or `cancelled` invoice by
deleting it. That leaves two gaps:

- **A paid invoice that turns out wrong can't be corrected.** `cancel_invoice` refuses paid
  invoices, and nothing records what the participant actually paid. `mark_invoice_paid` only
  changes the status.
- **Regeneration deletes invoices that have already left OpenZEV.** `Zev.next_invoice_number()`
  hands out a number when the draft is generated, and `_discard_replaceable_invoices` deletes a
  cancelled invoice together with its number. An approved invoice's PDF can be downloaded and handed
  over before anyone clicks "mark sent", so `sent_at` doesn't show whether a document went out
  either. The result is a gap in the number sequence that nothing explains, which conflicts with
  GeBüV retention.

The LEG billing spec (SPEC-2026-06-leg-billing-model §4.5.2) needs the same retention rule for
LEG documents and bases it on approval. Issue #388 asks for corrections of paid invoices, with the
amount already paid carried forward to the next invoice.

## Decision

- **Approval is the point of no deletion.** `Invoice.approved_at` is stamped when an invoice is
  approved and is never cleared, not even when the invoice is later cancelled. An invoice with
  `approved_at` set is *issued*. Regeneration and non-admin deletion only remove invoices that were
  never issued. A cancelled issued invoice is kept with its number for good.
- **What was paid is recorded as payments, not a status.** A `Payment` row holds the amount and the
  date. An invoice moves to `paid` once its payments cover the amount due. `mark-paid` records one
  payment for the outstanding amount.
- **A paid invoice is corrected by a credit note, through one function.** `correct_invoice` is the
  only path that leaves `paid`. A full reversal cancels the invoice and issues a credit note for the
  amount actually received. A partial credit issues a credit note and leaves the invoice as it is.
  Credit notes have their own number sequence per ZEV and copy the VAT rate and VAT mode of the
  source invoice.
- **A credit is applied after VAT and never makes an invoice negative.** A later invoice deducts
  open credits from its `total_chf` to get `amount_due_chf` (a derived property, not a stored column), floored at zero. Any remainder stays on
  the credit. `total_chf` keeps its meaning: the value of the invoice.
- **A participant/period may hold several invoices, but at most one that isn't cancelled.**
- **Invoices with a total of zero or less (net payouts to a producer) can't be corrected yet.**
  `correct_invoice` refuses them. A correction there would mean the participant owes money, which
  needs a negative credit. This is deferred, not rejected.

## Consequences

Positive:
- Invoice numbers have no unexplained gaps: every number that was issued still exists, either live
  or cancelled.
- A correction keeps the audit trail. The original, the credit note and the replacement can all be
  read, and each references the other.
- ZEV/vZEV and LEG follow one retention rule.
- Payments are the foundation for bank matching on the QR reference and for batch mark-paid.

Trade-offs:
- `total_chf` no longer equals "what is still owed". Every consumer (QR bill, email `{total_chf}`,
  period overview, dashboard revenue, the annual reports) has to choose between `total_chf` and
  `amount_due_chf`.
- Retained cancelled invoices appear in the period queries, which have to keep preferring the live
  invoice.
- An invoice with payments can no longer be cancelled directly or deleted. The payments have to be
  removed first, or the invoice corrected.

## Alternatives considered

1. Use `sent_at` as the retention marker (the original proposal in #388).
   - It misses approved invoices whose PDF was downloaded and handed over without "mark sent", and it
     would give LEG and ZEV/vZEV two different rules.
2. Let `cancel_invoice` accept paid invoices.
   - A cancellation would then drop the money that was received without leaving a record. Correcting
     a paid invoice has to issue a credit in the same transaction.
3. Put the credit on the next invoice as a negative line item.
   - The credit would be taxed at the new invoice's VAT rate rather than the original's, and the line
     items would no longer describe their own period. It stays possible later as a simplification for
     ZEVs that aren't VAT-registered.
4. Allow negative invoice totals instead of carrying credit forward.
   - The Swiss QR bill can't carry a negative amount.

## Notes

Specified in `docs/specs/2026-10-payments-and-credits.md`. Delivered in three PRs: payments and
`approved_at`, then credits and `correct_invoice`, then applying credits to invoices.
