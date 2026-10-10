# ADR 0032: One visual language for screen and documents

- Status: Accepted
- Date: 2026-10-08
- Amends: ADR 0014 (decision 1: separate screen and print typefaces; the "PDF-only" document anatomy)
- Related specs: `2026-08-ui-redesign-pdf-style` (baseline), `2026-04-frontend-management-page-design` (reference)

## Context

ADR 0014 made the app and its documents share tokens, brand and chart palette,
but deliberately not their layout grammar or typeface: the screen kept Inter,
print kept "Helvetica Neue". On the server, neither Helvetica nor Helvetica
Neue is installed, so every PDF actually rendered in Liberation Sans (an Arial
metric clone), with chart labels falling back to Noto Sans. The two surfaces
read as relatives rather than as one product:

- The invoice's most recognisable elements — the document header with its
  hairline and short forest rule, sections opened by a forest dot, figure tiles
  (kicker label, figure, small unit, one dark accent tile), the sage status pill
  — appeared nowhere in the app.
- The app's own chrome had drifted toward a generic dashboard: floating cards
  with large shadows, cards nested in cards for every list record, a solid
  primary button in every row, a top-right account card that cost a band of
  vertical space on every page, a sidebar whose 150px logo pushed navigation
  below the fold at 900px height.
- Two of the five document templates (annual statement, tax overview) predated
  the shared PDF base and used their own header, centred tiles and a static
  footer.

## Decision

1. **One typeface.** Inter is the face of the app and of every generated
   document. The backend images install Debian's `fonts-inter` (static OTFs,
   embedded as CFF subsets in PDF/A-3b); `design/tokens.json`
   `type.fontFamily.print` leads with `Inter` and the generator emits it as
   `--font-print` (`backend/templates/pdf/_tokens.css`) and
   `_CHART_FONT_FAMILY` (chart SVG roots, which do not inherit the document
   font). The screen face is emitted as `--font-sans`. The app loads Inter's
   optical-size axis, so display sizes use the display cut. **Exception:** the
   Swiss QR-bill payment part keeps the fonts its standard permits (the `qrbill`
   SVG renders in Liberation Sans).
2. **Shared anatomy, in both directions.** The document elements become the
   app's elements, and the remaining documents adopt them too:
   - *Header signature* — page headers (and dialog headers) end in a hairline
     with a short forest rule at its start, the documents' `.document-header`
     rule; the scope kicker is set in forest.
   - *Section heading* — sheet titles are set like the invoice's section
     headings: forest, bold, without decoration. (The first iteration put a
     forest dot before every title, kicker and document name; review dropped
     it — repeated everywhere, it carried no meaning — in the app and in the
     documents alike.)
   - *Figure tiles* — KPI tiles use the documents' tile: uppercase kicker
     label, the figure with its unit set small and muted, an optional hint,
     at most one dark accent tile per view. Tiles in a row share label/figure/
     hint tracks (CSS subgrid), so figures align like a printed row.
   - *Status pill* — approved invoices wear the sage pill printed on the
     invoice; table and list pills follow its fill-plus-hairline grammar.
   - *Tables* — column labels are small white uppercase kickers on the
     documents' dark forest header band (`--brand-deep`), sticky. A table
     fills its sheet edge to edge, as line items fill a document's measure:
     the band meets the sheet's sides, and its rounded top when the table
     opens the sheet; money and quantities are tabular and right-aligned.
   - *Charts* — one energy palette from the brand, on screen and in the PDFs:
     forest for production and energy from the community, amber for the grid,
     sage for feed-in, slate for consumption, dark ink for percentage lines
     (no teal, violet or blue ramps).
   - The annual statement and the tax overview move onto
     `pdf/shared_pdf_base.html`, which now also holds the summary band
     (recipient + facts), figure tiles, sections, dark-header
     `doc-table`, `summary-box` and the running footer used by all documents.
3. **A quieter shell.** The sidebar is deep forest beside the paper
   workspace, like the documents' dark header band: a horizontal logo lockup,
   compact navigation that fits a 900px viewport, the current page as a
   lighter forest row with a short gold mark (gold only on the dark, as on
   the invoice's savings card), and the signed-in account at its foot
   (account, language, log out, and the source link as the panel's last line)
   instead of a top bar. The
   sidebar names no scope: the community is named — and chosen — in each
   page's scope line, the kicker above the title, which opens the list of the
   account's communities when there is more than one (the documents, too,
   name their issuer once, above the title). On phones a white app bar carries the menu button and
   the lockup. Forest is kept for what matters — the current page, the primary
   action, the one accent figure — as the documents keep it for their rule,
   table headers and accent card. Sheets are white with a hairline and no
   floating shadow; depth is reserved for menus, dialogs and toasts.
4. **Lists are ledgers, actions have one weight per level.** Management lists
   (participants, metering points, tariffs) are hairline-separated rows of one
   sheet, not cards in a card. Toolbars sit on the page without a sheet. Inside
   rows, the main action is a forest outline and destructive actions are quiet
   until hovered; the page's own primary action is the only solid button, and
   confirm dialogs keep the solid red.

## Consequences

Positive:
- A participant who opens the app and then the PDF sees the same typeface,
  figures, pills, headings and rules — the documents read as printouts of the
  app, and the app as the live version of the documents.
- PDFs gain a typeface designed for screens and small sizes (tabular figures
  where the templates ask for them), and chart labels no longer fall back to a
  third face.
- Every page gains vertical room (no top bar, compact sidebar); the
  participant list is about 40% shorter; row actions no longer compete with the
  page's primary action.
- One set of document components in the PDF base instead of per-template
  copies.

Trade-offs:
- The backend image grows by the Inter OTFs (~21 MB installed). Deployments that build
  their own image must add `fonts-inter`; without it the stack falls back to
  the previous Helvetica/Arial chain and documents still render.
- Inter is wider than Liberation Sans: some long line-item descriptions wrap
  one line earlier. Page geometry (QR slip, running furniture) is unchanged.
- Stored `PdfTemplate` overrides keep their own markup; the changed shared base
  flags them stale through the existing `default_digest` check.
- The app's labels and table headers are uppercase kickers (via CSS
  `text-transform`, never in translation strings), as on the documents; they
  are kept short and set at 11px with tracking.

## Alternatives considered

1. **Keep two typefaces (ADR 0014 decision 1).** Rejected: the "print face" was
   in practice whatever metric clone the container had, and it was the single
   biggest visible difference between app and documents.
2. **Helvetica-like face on screen.** Rejected: Inter is the better screen face
   and is free to embed; moving the documents to it costs one package.
3. **Ship the font inside the templates as a `data:` URI.** Rejected: every
   render would carry ~300 KB of base64, and stored overrides would have to copy
   it; a system font keeps templates small and the fetcher policy unchanged.
4. **A white sidebar.** Shipped for a while, out of concern that the large
   dark area would outweigh the content and compete with the forest accents
   that carry meaning (current page, primary action, accent figure). Replaced
   in review by the deep-forest sidebar, which matches the documents' dark
   header band as the table headers do.
5. **A pale forest table header (the dark band at screen weight).** Shipped
   first, out of concern that a dark band on every table would outweigh the
   content and the primary action. Replaced in review: with the darker page
   tone and the deep-forest primary button, the dark band ties each table to
   the documents' line items without dominating, and the pale band read as a
   tint rather than as the documents' header.
6. **Copy the PDF layout 1:1 onto screens (a "document" app).** Rejected for the
   reasons in ADR 0014: dense operational screens need sentence-case labels in
   forms, light table bands, and no gradient chrome — the shared elements are
   the ones that carry meaning (rules, dots, tiles, pills, type), not the page
   geometry.
7. **Keep the community switcher in the sidebar.** The usual workspace-switcher
   place, and where it was. Rejected in review: the page's scope line already
   named the community right under it, so every page said it twice, and the
   switcher card (plus a platform chip of the same height) made the sidebar
   top heavy. In the scope line the name and the choice are one element, it
   works the same with a collapsed rail and on phones (no drawer to open), and
   the sidebar keeps only the logo, the navigation and the account.

## Notes

- Tokens: `design/tokens.json` (`--line-strong`; semantics `--text-heading`,
  `--border-strong`, `--surface-sunken`, `--accent-rule`, `--sidebar-text`,
  `--sidebar-hover`, `--sidebar-line`; field tokens 14px/500 labels, 8px radius).
- Specs: `2026-08-ui-redesign-pdf-style.md` §15, `2026-04-frontend-management-page-design.md`.
