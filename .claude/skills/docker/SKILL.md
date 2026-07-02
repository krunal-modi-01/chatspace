---
name: docker
description: Containerization — building minimal, secure, reproducible images with multi-stage builds, ordering layers for cache efficiency, running as non-root, adding healthchecks, scanning images for vulnerabilities, and Compose for local development. Use when writing or reviewing a Dockerfile, shrinking/hardening an image, fixing slow or cache-busting builds, or setting up local multi-service dev with Compose. Used by the devops-engineer and infrastructure-engineer agents.
---
# Docker Skill

## Purpose
Produce container images that are small, secure, reproducible, and fast to build: multi-stage builds that ship only runtime artifacts, layer ordering that maximizes cache hits, a non-root runtime, real healthchecks, and a scanned, pinned supply chain. Local Compose mirrors the shape of production without becoming production.

## When invoked
- The **devops-engineer** and **infrastructure-engineer** agents use this when authoring/reviewing Dockerfiles, optimizing image size or build time, hardening the runtime, or wiring up local Compose.
- Triggered by: "write/review the Dockerfile", "the image is huge/slow to build", "run as non-root", "add a healthcheck", "scan the image", "set up local services with Compose".
- Pairs with `security` (supply chain, secrets), `backend`/`frontend` (what's being packaged), and CI/CD pipelines.

## Inputs
- The application, its language/runtime, build steps, and runtime entrypoint.
- Runtime needs: ports, env/config, secrets, dependencies (DB, cache), health signal, resource limits.
- Target registry and platform (amd64/arm64), and the org's base-image and scanning policy.

## Outputs
- A multi-stage `Dockerfile` producing a minimal, non-root image with a pinned base and a healthcheck.
- A `.dockerignore` that keeps build context small and secrets out.
- A `docker-compose.yml` for local development (app + dependencies), if requested.
- Image scan results and a pinned dependency/base story.

## Procedure
1. **Pick a minimal, pinned base.** Prefer the smallest base that runs your app: distroless or `-slim`/`alpine` variants, or `scratch` for static binaries. Pin by digest or specific tag (`python:3.12.4-slim`, not `latest`) for reproducibility. Smaller base = smaller attack surface and faster pulls.
2. **Use multi-stage builds.** A `build` stage with the full toolchain compiles/installs; the final `runtime` stage `COPY --from=build` only the artifacts needed to run. Build tools, dev headers, and source never reach the shipped image. This is the single biggest lever on size and attack surface.
3. **Order layers for cache efficiency — least-changing first.** Copy and install dependencies (using only the manifest/lockfile) *before* copying application source, so a code change doesn't invalidate the dependency layer:
   - copy lockfile → install deps → copy source → build.
   Combine related `RUN` steps and clean package caches in the same layer (`apt-get ... && rm -rf /var/lib/apt/lists/*`) so cleanup actually reduces layer size. Use BuildKit cache mounts for package caches where available.
4. **Write a tight `.dockerignore`.** Exclude `.git`, `node_modules`, build output, local env files, and anything secret. A bloated context slows builds and risks leaking files into the image.
5. **Run as non-root.** Create a dedicated user/group and `USER` down before the entrypoint. Ensure file permissions allow the app to run but not to write where it shouldn't. Root-in-container is a container-escape amplifier — avoid it by default.
6. **Never bake in secrets.** No API keys/passwords in `ENV`, `ARG`, or layers (they persist in history even if later removed). Inject secrets at runtime (orchestrator secrets, mounted files) or use BuildKit `--secret` for build-time-only credentials.
7. **Add a HEALTHCHECK** that reflects real readiness (hits an app health endpoint or checks the process can serve), with sensible `interval`/`timeout`/`retries`/`start-period`. Orchestrators use it to route traffic and restart unhealthy containers.
8. **Set a correct entrypoint and signal handling.** Use exec-form `ENTRYPOINT`/`CMD` (`["app"]`) so signals reach the process (PID 1). Add a lightweight init (`--init` / tini) if the app doesn't reap children. Handle SIGTERM for graceful shutdown.
9. **Make it deterministic and multi-arch as needed.** Pin dependency versions via lockfiles; avoid network-nondeterministic build steps. Build for the target platform(s) with buildx when arm64/amd64 both matter.
10. **Scan and slim before shipping.** Run a vulnerability scanner (Trivy/Grype/registry scanning) on the built image; fail CI on fixable high/critical findings. Verify final size and layer count. Rebuild base images regularly to pick up security patches.
11. **Compose for local only.** Define app + dependencies (db, cache, queue) with named volumes for data, a shared network, `depends_on` with healthchecks for ordering, and env from a local `.env` (git-ignored). Bind-mount source for hot reload in dev. Keep Compose as a dev convenience — do not treat it as the production deployment.

## Best practices
- Multi-stage always; ship runtime artifacts, never the build toolchain.
- Pin base images and dependencies; rebuild regularly to absorb patches.
- Dependency layer before source layer — protect the cache.
- Non-root user, exec-form entrypoint, real healthcheck, graceful SIGTERM.
- Keep the context tiny with `.dockerignore`; keep secrets out of image history.
- Scan in CI and gate on fixable criticals; track image size as a budget.

## Anti-patterns
- **`FROM ...:latest`** and unpinned deps — non-reproducible builds and surprise breakage.
- **Single-stage image carrying the full build toolchain** — huge and attack-surface-heavy.
- **Copying source before installing deps** — every code change busts the dependency cache; slow builds.
- **Running as root** by default.
- **Secrets in `ENV`/`ARG`/layers** — they live forever in image history.
- **No `.dockerignore`** — bloated context, leaked files, slow builds.
- **Shell-form entrypoint** that swallows signals → containers that won't stop gracefully.
- **`apt-get install` without cleaning caches in the same layer** — cleanup in a later layer doesn't shrink the image.
- **Using Compose as the production deployment.**
