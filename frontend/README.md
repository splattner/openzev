# OpenZEV frontend

React + TypeScript + Vite single-page application for the OpenZEV energy
community management platform. See the root `README.md` for full-stack setup;
this file covers frontend-only development.

## Stack

- React 19, TypeScript, Vite
- TanStack Query for server state
- react-i18next for localization (EN/DE/FR/IT)
- Mantine for components (shared `DataTable` built on `@tanstack/react-table`), Recharts for charts
- Vitest for unit tests, Playwright for user-guide screenshots

## Local development

Use the Node version pinned in `.node-version` (currently 24.20.0).

```bash
npm install
cp .env.example .env   # set VITE_API_BASE_URL (see root README)
npm run dev            # http://localhost:5173
```

The dev server proxies API requests to the backend; the API URL comes from
`VITE_API_BASE_URL` in `.env`.

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server with HMR |
| `npm run build` | Type-check (`tsc -b` on TypeScript 7) + production build to `dist/` |
| `npm run lint` | ESLint |
| `npm run test:unit` | Vitest unit tests (one-shot) |
| `npm run test:unit:watch` | Vitest watch mode |
| `npm run screenshots` | Playwright: regenerate user-guide screenshots into `../docs/user-guide/screenshots/` |
| `npm run preview` | Serve the production build locally |

Two TypeScript versions are installed on purpose. `typescript-native` is
TypeScript 7, the native compiler, and type-checks in `npm run build`.
`typescript` stays on 6.0 because typescript-eslint does not support 7 yet.
Both packages provide a `tsc` executable, so the build calls the native
compiler by its package path to avoid ambiguity.
Once typescript-eslint supports 7, drop the alias, move `typescript` to 7,
remove its version cap in `renovate.json`, and use plain `tsc -b` in the build.

After pulling dependency changes, run `npm ci`. An existing dev stack keeps
its dependencies in the `frontend_node_modules` volume; refresh it from the
repository root with `docker compose -f docker-compose.dev.yml exec frontend npm ci`
(or `podman compose`). Restarting the frontend container alone does not
update that volume.

## Project layout

- `src/pages/` — route components
- `src/features/` — domain-scoped hooks, forms and components (invoices,
  tariffs, metering points, participants, feasibility, admin)
- `src/lib/` — shared utilities, API client and date helpers
- `src/i18n/locales/` — translation files (all user-facing text must go
  through i18n; never hardcode UI strings)
- `src/types/api.ts` — API contract types (keep in sync with the backend
  serializers)
- `tests/` — unit tests
- `screenshots/` — Playwright configuration used by `npm run screenshots`

## Conventions

- Prefer small, targeted changes; preserve existing style and naming.
- Update `src/types/api.ts` when backend response shapes change.
- When changing API behavior, update backend tests and frontend consumers
  together.
