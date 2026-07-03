# chatspace frontend

React + TypeScript SPA (Vite) for chatspace. This is the T08 app skeleton:
routing with a protected/public split, Tailwind CSS, a typed REST client
(`Authorization: Bearer` injection + 401→refresh), an auth store (access
token, refresh token, current user), and base RFC 7807 `problem+json` error
surfacing. Feature screens land in T30+.

## Setup

```bash
npm install
cp env.example .env.local   # set VITE_API_BASE_URL to the backend's /v1 base path
npm run dev
```

## Scripts

- `npm run dev` — start the Vite dev server
- `npm run build` — typecheck + production build
- `npm run typecheck` — `tsc -b --noEmit`
- `npm run lint` — `oxlint`
- `npm run test` — run the vitest suite once
- `npm run test:watch` — vitest in watch mode

## Structure

- `src/api/` — typed REST client (`httpClient.ts`), problem+json parsing
  (`problem.ts`), wire types (`types.ts`), and per-domain API functions
  (`authApi.ts`).
- `src/store/` — Zustand auth store (`authStore.ts`) and the token
  persistence abstraction (`tokenStorage.ts`) that isolates
  localStorage/cookie choices from the rest of the app.
- `src/hooks/` — client-side business logic extracted out of JSX
  (session bootstrap, login form, logout).
- `src/components/` — route guards (`ProtectedRoute`, `PublicOnlyRoute`),
  the authenticated app shell, and shared UI (`ErrorBanner`).
- `src/pages/` — route-level screens.
- `src/config/env.ts` — env-based configuration (API base URL).

## Conventions

Functional components only, one per file, no inline business logic in
JSX — extract to hooks/services (see `CLAUDE.md`).
