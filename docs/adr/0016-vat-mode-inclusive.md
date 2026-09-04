# ADR 0016: Explicit VAT mode, with an "inclusive" treatment for non-registered ZEVs

- Status: Accepted
- Date: 2026-09-04

## Context

OpenZEV's VAT handling was a single implicit switch: if `Zev.vat_number` was
set, the billing engine added VAT on top of the subtotal; if not, VAT was 0%
and tariff prices were billed verbatim.

That leaves a real case unserved. A ZEV that is **not** VAT-registered
(turnover under CHF 100k, no voluntary registration — the common case for a
small residential community) still buys in electricity, grid usage, the
Netzzuschlag, cantonal/communal levies and metering **with VAT it cannot
reclaim**. Its true cost is `net × 1.081`. Billing participants the net prices
under-recovers by the VAT rate on every grid-side line.

The prices such a ZEV should bill are therefore VAT-inclusive. The old
implementation supports that only by entering every tariff gross by hand —
and the Art. 7b / VSE tariff import (issue #507) writes **net** prices, so
every yearly re-import silently reverts them. See issue #542.

## Decision

Replace the implicit switch with an explicit `Zev.vat_mode` (`VatMode`
TextChoices), and add a third treatment:

- `not_registered` (default) — prices billed as entered, no VAT line.
- `registered` — prices are net, the engine adds the active `VatRate` on top,
  the invoice shows a VAT line. `vat_number` is required in this mode.
- `inclusive` — the ZEV is not registered but its bought-in costs carry
  non-recoverable VAT. Tariff prices stay **net in storage**; at invoice time
  the engine multiplies each VAT-bearing line's total by `1 + rate` before
  rounding, so the derived unit price is gross too. No VAT line appears (a
  non-registered issuer must not show one). The folded-in VAT is summed into
  `Invoice.embedded_vat_chf` for the operator's own records; it is never
  shown on the participant invoice or annual statement.

Key points:

- A tariff **bears input VAT** when its category is `grid_fees`, `levies` or
  `metering`, or its category is `energy` with `energy_type = grid`. Local
  (solar) energy and the feed-in credit are excluded — no input VAT is paid on
  own production, and the feed-in credit is money paid out.
- The rate is resolved once, at `period_end`, exactly as `registered` resolves
  it. No active rate → no grossing.
- Data migration: every ZEV with a non-empty `vat_number` moves to
  `registered`; everyone else stays `not_registered`. No invoice changes.
- `vat_number` is now required for `registered` and forbidden for the other
  two modes (`Zev.clean()` + serializer validation).

## Consequences

Positive:
- The non-registered-with-VAT case is billed correctly with no manual price
  entry.
- Stored tariffs always match the grid operator's published (net) figures, so
  the yearly tariff re-import is idempotent — no re-grossing, no "was this row
  already grossed?" state to track.
- Changing VAT status later (e.g. crossing CHF 100k and registering) is a
  one-field change, not a mass re-pricing of every tariff.
- `registered` behaviour is byte-for-byte unchanged.

Trade-offs:
- A new engine branch plus the `_tariff_bears_input_vat` classifier, which has
  to be correct — a misclassification misprices. This is inherent complexity
  (which costs carry input VAT is a real-world fact), not accidental.
- `embedded_vat_chf` adds a field to `Invoice`, its serializers, and the
  transfer archive.
- A ZEV on `inclusive` still shows "not VAT-liable" on the participation
  contract, with no note that prices are VAT-inclusive. Acceptable for now;
  can be revisited.
- The tariff page (history list and price chart) shows the stored **net**
  prices, not the gross amounts invoices bill. A page-level notice is shown
  when `vat_mode = inclusive` to name the gap; the numbers themselves are not
  grossed there, because the net figure is the one that reconciles against
  the operator's published sheet.
- The financial summary does not yet surface `embedded_vat_chf`; the value is
  on the API and can be added to that operator-facing report later.

## Alternatives considered

1. **A toggle on the tariff import that grosses prices up on the way in.**
   Rejected: it stores a derived number (`net × 1.081`) in the tariff, so the
   stored data stops matching the operator's sheet, every re-import has to
   re-gross, and there is per-row state to track about whether grossing was
   applied. It also puts a property of the *legal entity* (VAT status) onto
   individual tariff rows.

2. **Keep the implicit `vat_number` switch and document "enter tariffs
   gross".** Rejected: it is exactly today's behaviour, and the friction
   (manual grossing, re-import reverting it) is the reason #542 was filed.

## Notes

- Spec: `docs/specs/2026-03-tariffs-and-billing-engine.md` §4.8;
  `docs/specs/2026-03-admin-governance-and-settings.md` §4.
- Issue: #542. Design discussion in that issue's comments.
