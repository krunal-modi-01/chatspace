# syntax=docker/dockerfile:1
#
# Local-development image for the chatspace frontend (Vite + React).
#
# T37 scope is the *local full stack* (docker-compose up --build), not a
# production build/deploy (T40) — so this image runs the Vite dev server
# with hot-module-reload against a bind-mounted `./frontend` (see
# `docker-compose.yml`), rather than shipping an nginx-served production
# bundle. No secret/config is baked in: `VITE_API_BASE_URL` is injected at
# container start via docker-compose env, matching `frontend/env.example`.

FROM node:24-slim AS base

# `node:*-slim` already ships a non-root `node` user (uid/gid 1000) — reuse
# it rather than creating a second uid/gid-1000 identity (which collides).
WORKDIR /app

# Dependency layer first — only the manifest/lockfile are needed to
# `npm ci`, so editing source never busts this cache layer. `npm install`
# (not `npm ci`) is used deliberately: different npm releases resolve
# optional platform-specific transitive deps (e.g. wasm fallbacks for
# native binaries like lightningcss/rollup) slightly differently, which
# makes `npm ci`'s strict lockfile-parity check spuriously fail across npm
# versions even though the lockfile itself is valid and unchanged.
# `--no-audit --no-fund` keep the build output quiet and deterministic.
COPY package.json package-lock.json ./
RUN npm install --no-audit --no-fund

# Application source is bind-mounted over this at `docker-compose up` time
# for hot reload; this COPY keeps the image runnable standalone too (e.g.
# `docker build` + `docker run` without compose).
COPY . .

RUN chown -R node:node /app

USER node

EXPOSE 5173

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD node -e "fetch('http://localhost:5173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
