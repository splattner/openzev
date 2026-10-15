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
| `pages` | `pages/*` |
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
| `pages/` | Rules used by one page or feature (metering points, tariffs, billing period, …) |
| `utilities.css` | Single-property spacing helpers (`mt-1`, `mb-15`, …) |
| `misc.css` | Leftovers from the split that have no better home yet (some may be dead); layer `components` |

Rules of thumb: a class used by two or more pages belongs in `components/`; a class
used by one page belongs in `pages/`. Colours come from `var(--…)` tokens; the
alpha-only exceptions are listed per file in `scripts/hex-migration-allowlist.json`.
