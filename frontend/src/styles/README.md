# Stylesheets

`index.css` is the only entry point (imported by `main.tsx`). It declares the cascade
layers once and `@import`s every file into one of them:

```
@layer native, vendor, tokens, base, layout, components, pages, responsive, utilities;
```

| Layer | Holds |
| --- | --- |
| `native` | `native-controls.css`: native element defaults a Mantine class must beat |
| `vendor` | Mantine, Mantine dates and Leaflet CSS |
| `tokens` | `tokens.css` |
| `base` | `base.css` |
| `layout` | `layout/*` except `responsive.css` |
| `components` | `components/*` and `misc.css` |
| `pages` | `pages/*`, then the stylesheets that sit next to their page or component |
| `responsive` | `layout/responsive.css`: the media-query overrides of components and pages |
| `utilities` | `utilities.css` |

A rule in a later layer beats one in an earlier layer whatever its selector specificity,
so a page rule overrides a component rule, and ours override Mantine's, without selector
tricks (`:where()`, doubled classes, `:not()`). Put the override in the later layer instead.
Inside a layer nothing changed: specificity first, then later imports win ties, so the
import order within a layer is still part of the behaviour. Add a new file by importing it
into its layer, where it belongs in that layer.

Because layers rank before specificity, **write a page rule for the element it means**:
`td.tariff-table-unit`, not `.tariff-table-unit`, when the same class sits on a `th` that
a component styles as the table band. A bare class used to lose to the band on
specificity; now it wins. When a page rule is meant to beat a component rule, that is the
whole point; when it is not, scope it.

**Never leave CSS outside a layer.** Unlayered rules beat every layer. Third-party
stylesheets are imported in `index.css` with `layer(vendor)`, not from a component.
Styles libraries inject at runtime (Mantine's `<style>` for CSS variables and style
props) are unlayered and win; they only set what the component was asked to set.

| Folder / file | Holds |
| --- | --- |
| `tokens.css` | Generated design tokens (`design/tokens.json`) — never edit by hand |
| `base.css` | `:root` scale (radius, shadow), reset, typography, field-token sizing of native inputs (skips Mantine's own) |
| `native-controls.css` | Native element defaults a Mantine class must beat (labels, checkbox width); layer `native` |
| `layout/` | App shell, sidebar, account menu, page header, footer; `responsive.css` is its own `responsive` layer |
| `components/` | Shared, reusable pieces: tables, sheets, stat tiles, buttons, badges, dialogs, … |
| `pages/` | Page-level rules shared by several pages: sign-in shell, form grids, invoice rows, public card |
| `utilities.css` | Single-property spacing helpers (`mt-1`, `mb-15`, …) |
| `misc.css` | Leftovers from the split that have no better home yet (some may be dead); layer `components` |

## Where a rule lives

CSS used by exactly one page or component sits **next to it**, named after it:
`features/tariffs/TariffDetailDrawer.css`, `pages/LoginPage.css`,
`components/PeriodSelector.css`. A rule shared by a component and the one page that
renders it goes in the page's file. Only what several pages share stays here:
shared primitives (sheet, table, buttons, badges, dialogs, stat tiles) in `components/`,
shared page-level rules in `pages/`. When you delete a component, delete its stylesheet
and its import with it.

Co-located files keep the global class names; don't convert them to CSS Modules. The
design system is a shared global vocabulary. Use `*.module.css` only for a new, genuinely
local component.

A co-located file is imported **from `index.css`**, into the `pages` layer (append it to
the end of that block), not from the component. Routes are lazy-loaded, so a stylesheet
imported by a component would ship with its route chunk and land in the cascade whenever
that route first loads, which makes the order inside the layer depend on navigation.
When a component goes, its stylesheet goes with it, and the build fails on the
leftover `@import` until that goes too. A media query that only overrides the file's own rules goes in an
`@media`/`@container` block after them, in the same file; one that has to beat a rule
from another file still goes in `layout/responsive.css`.

Colours come from `var(--…)` tokens; the alpha-only exceptions are listed per file in
`scripts/hex-migration-allowlist.json` (paths relative to `src`, so they move with the
file).
