# ADR 0045: Delivered documents are immutable, held as their own copy, and addressed to the participant

- Status: Accepted
- Date: 2026-11-05

## Context

[SPEC-2026-11-participant-document-inbox](../specs/2026-11-participant-document-inbox.md)
([#862](https://github.com/splattner/openzev/issues/862)) adds a list of documents that were delivered
to a participant. Three existing facts shape it:

- **What a participant downloads is a live render, or a file that can change.** The annual statement,
  financial summary and tariff overview are rendered per request. `Invoice.pdf_file` is cleared on
  approval and re-rendered by `save_invoice_pdf`, which the `generate-pdf` action runs at any status.
  `ContractIssue` is the exception: a versioned, immutable snapshot ([ADR 0037](0037-issued-invoices-are-corrected-not-deleted.md)
  applies the same principle to invoices themselves).
- **Access to the same participant's data already has two lifetimes**, encoded as per-viewset exceptions
  in `ZevScopedQuerySetMixin`: live data ends at `valid_to`; sent invoices outlive it
  (`participant_access_survives_end`, #761/#861). Each new participant-visible resource would need its
  own exception.
- **Parties and accounts are separate** ([ADR 0028](0028-zev-parties-and-dated-roles.md),
  [ADR 0027](0027-per-zev-access-grants.md)): a participant exists whether or not anyone logs in as
  them, and an account can be linked to several participant rows.

The notification center keeps notices for current members only, so it cannot be the record of what was
delivered, and anonymisation (#793) needs a rule for documents that name a person.

## Decision

1. **A delivered document is a fact, written once.** An `inbox.DeliveredDocument` row records that a
   file reached a participant. Its content never changes; only `superseded_*` and `withdrawn_*` are set
   later. A correction is a new document that supersedes the old one, never an edit.
2. **The inbox holds its own copy of the bytes.** For invoices and reports the stored file is the exact
   bytes delivered (the email attachment, for an emailed invoice), with a `sha256`. A contract is the
   exception: it references `ContractIssue.pdf`, which is already an immutable snapshot, so no second
   copy exists that could disagree.
3. **Addressed to the participant row, not to an account.** Visibility is `participant__user`. The inbox
   fills before an account exists and is visible as soon as one is linked; an account linked to several
   rows sees all of them. Unlinking the account (which anonymisation does) ends access without touching
   the documents.
4. **Two access lifetimes, stated once.** Live data follows the participant link and ends at `valid_to`.
   The inbox has no end date and survives a disabled ZEV. This is the single exception, implemented as
   one opt-in attribute on the scoping mixin (`participant_survives_disabled_zev`), not as copies of
   the invoice-specific rule.
5. **Delivery is explicit where handing over is a decision.** Invoices enter the inbox when they are
   sent, because sending *is* the delivery. Contracts, annual statements, financial summaries and
   tariff overviews enter only when the operator delivers or issues them: a `ContractIssue` is also
   minted by a manager previewing a contract, and a statement can be corrected until the operator is
   satisfied.
6. **No read receipts.** The only fact stored is when the document was delivered. Downloads are not
   audited; email delivery status stays in `EmailLog`.
7. **After a cut-over, the inbox is the only participant path to these documents.** Managers and admins
   keep the live endpoints. The cut-over ships in a later release than the inbox, so existing users and
   the MCP tools are never left without a path.

## Consequences

Positive:
- "What did I receive?" and "what did we send them?" have one answer, from one table.
- A document a participant downloads next year is byte-identical to the one they were sent.
- The former-participant rule needs no per-endpoint exception for new document types.
- Anonymisation (#793) has a clear contract: unlink the account, leave the documents.

Trade-offs:
- Storage is duplicated for invoices (the inbox copy beside `Invoice.pdf_file`); a broadcast upload
  stores one file for many rows. A person who holds several participant rows gets one copy of a
  broadcast, on the first row; rows without an account are addressed one by one.
- Relinking a participant row to a different account gives that account the row's history. The row is
  the relationship, so this is by design, and is covered by the existing link audit events.
- A document delivered to the wrong participant cannot be recalled for invoices and reports (they are
  superseded, not withdrawn); only operator documents can be withdrawn.
- The mixin gains a second opt-in attribute to reason about.
- Until the cut-over, two paths to invoices coexist and the backfill must be accurate.

## Alternatives considered

1. **A view over the existing tables** (invoices, contract issues, reports).
   - The reports are not stored, the invoice file can change, and operator documents have no table;
     a union also keeps one access rule per source, which is the problem being removed.
2. **Always reference the source row, never copy.**
   - Correct for `ContractIssue` and adopted there. For invoices the source file is replaced by
     re-rendering, so a reference cannot promise "what was sent".
3. **Address documents to accounts.**
   - Breaks the participant without an account, and #761 separated the two on purpose.
4. **Deliver every `ContractIssue` and every report automatically.**
   - Pushes previews and uncorrected year-end figures to participants.
5. **Use the notification center as the record.**
   - Notifications are transient events for current members and are pruned by the privacy sweep.

## Notes

Phases and tests are in the spec. #793 is expected to read decision 3 and the spec's §6.3.
