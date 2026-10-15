# Stylesheets

`index.css` is the only entry point (imported by `main.tsx`). It declares the cascade
layers once and `@import`s every file into one of them:

```
@layer native, vendor, app;
```

| Layer | Holds |
| --- | --- |
| `native` | `native-controls.css`: native element defaults a Mantine class must beat |
| `vendor` | Mantine, Mantine dates and Leaflet CSS |
| `app` | Everything below, in the import order of `index.css` |

A rule in a later layer beats one in an earlier layer whatever its selector specificity,
so our rules beat Mantine's without selector tricks. Inside `app` nothing changed: later
files win ties and the order is part of the behaviour, so add a new file by importing it
where it belongs, not at the end by default.

**Never leave CSS outside a layer.** Unlayered rules beat every layer. Third-party
stylesheets are imported in `index.css` with `layer(vendor)`, not from a component.
Styles libraries inject at runtime (Mantine's `<style>` for CSS variables and style
props) are unlayered and win; they only set what the component was asked to set.

Splitting `app` into finer layers (layout, components, pages, …) would let the specificity
workarounds go, but it flips every place where a component rule currently wins by
specificity over a page rule (hover states, container queries, table bands). Do it
file by file, checking each, not in one move.

| Folder / file | Holds |
| --- | --- |
| `tokens.css` | Generated design tokens (`design/tokens.json`) — never edit by hand |
| `base.css` | `:root` scale (radius, shadow), reset, typography, field-token sizing of native inputs (skips Mantine's own) |
| `native-controls.css` | Native element defaults a Mantine class must beat (labels, checkbox width); layer `native` |
| `layout/` | App shell, sidebar, account menu, page header, responsive shell, footer |
| `components/` | Shared, reusable pieces: tables, sheets, stat tiles, buttons, badges, dialogs, … |
| `pages/` | Rules used by one page or feature (metering points, tariffs, billing period, …) |
| `utilities.css` | Single-property spacing helpers (`mt-1`, `mb-15`, …) |
| `misc.css` | Leftovers from the split that have no better home yet (some may be dead) |

Rules of thumb: a class used by two or more pages belongs in `components/`; a class
used by one page belongs in `pages/`. Colours come from `var(--…)` tokens; the
alpha-only exceptions are listed per file in `scripts/hex-migration-allowlist.json`.
