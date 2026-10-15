# Stylesheets

`index.css` is the only entry point (imported by `main.tsx`). It `@import`s every
file below **in cascade order** — later files win ties, so the order is part of the
behaviour. Add a new file by importing it where it belongs, not at the end by default.

| Folder / file | Holds |
| --- | --- |
| `tokens.css` | Generated design tokens (`design/tokens.json`) — never edit by hand |
| `base.css` | `:root` scale (radius, shadow), reset, typography, native form controls |
| `layout/` | App shell, sidebar, account menu, page header, responsive shell, footer |
| `components/` | Shared, reusable pieces: tables, sheets, stat tiles, buttons, badges, dialogs, … |
| `pages/` | Rules used by one page or feature (metering points, tariffs, billing period, …) |
| `utilities.css` | Single-property spacing helpers (`mt-1`, `mb-15`, …) |
| `misc.css` | Leftovers from the split that have no better home yet (some may be dead) |

Rules of thumb: a class used by two or more pages belongs in `components/`; a class
used by one page belongs in `pages/`. Colours come from `var(--…)` tokens; the
alpha-only exceptions are listed per file in `scripts/hex-migration-allowlist.json`.
