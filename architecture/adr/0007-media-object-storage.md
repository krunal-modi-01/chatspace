# ADR-0007: Media storage — S3-compatible abstraction, validate-through-app, separate-origin signed URLs

> Owner: `architect` / `documentation-writer`. Indexed in `architecture/adr/README.md`.

- **Status:** Proposed (direction human-confirmed; provider choice deferred to deploy time)
- **Date:** 2026-07-02
- **Deciders:** architect + human architecture gate
- **Tags:** storage, security, media

## Context
v1 supports media attachments (images, files, video) on channel and DM messages (F57–F62, R30–R33/R42/R53) with strict hygiene:
- Per-type size caps (image 10 MB, file 50 MB, video 200 MB) and content-type allowlist; **content sniffing must match the declared type**; `image/svg+xml` excluded (F58).
- **EXIF (incl. GPS) stripped from images before storage**, or the upload is rejected (F61/R53).
- Filename sanitisation; per-user upload rate limit (20/min); orphaned-upload cleanup (F62).
- Media served from a **separate origin/bucket** via **short-TTL (5 min) signed URLs**, authorised against **current** membership; access revoked within the TTL after membership ends (F59, R32).
- **No server-side transcoding/resizing** (§2 non-goals); render inline if browser-decodable else download (F60).
- No AV/malware scanning in v1 (accepted risk).

The human confirmed the direction: an **S3-compatible abstraction via boto3** — MinIO locally, any S3 provider in prod (AWS S3 / Cloudflare R2 / DO Spaces) — with the concrete provider chosen at deploy time.

The forcing question is settled in direction; this ADR records the upload/serve topology and hygiene pipeline.

## Decision
We will store media in an **S3-compatible object store accessed via boto3**, behind a thin internal storage-service interface so the concrete provider is a deploy-time config choice (endpoint, bucket, credentials via env / `pydantic-settings`). Local dev uses **MinIO**; prod uses a provider TBD at deploy (R2 / S3 / Spaces). Topology:

- **Upload path (through the app):** client → app (multipart) → the media service validates size + declared content-type against the allowlist (F58), **sniffs** actual bytes and rejects on mismatch or SVG (415), **strips EXIF for images** (Pillow) or rejects the malformed image (F61), **sanitises the filename**, then `put_object` to the bucket under an opaque key. Upload must go through the app (not direct browser→bucket PUT) precisely because sniffing and EXIF-strip require the server to see the bytes.
- **Two-phase association + orphan cleanup:** media is uploaded, then associated with a message on message-create; a scheduled cleanup job removes objects whose parent message-create never completed (F62).
- **Serve path (separate origin, signed URLs):** on fetch, the app checks the requester's **current** channel/DM membership (F34/F59), then returns a **5-min presigned GET URL** pointing at the bucket's separate origin. The client fetches bytes directly from the bucket. A removed member loses access within the 5-min TTL (bounded revocation lag, documented risk).
- **Rendering:** the client renders browser-decodable images/video inline and everything else as a download affordance with filename + size; **no transcoding** (F60).

## Options considered
| Option | Pros | Cons |
|--------|------|------|
| A (chosen) — S3-compatible via boto3, validate-through-app, separate-origin 5-min presigned GET | Provider-portable (MinIO/S3/R2/Spaces) fits self-hostable ethos; app sees bytes so sniff + EXIF-strip + sanitise are enforceable; separate origin + short-TTL signed URLs give bounded, membership-scoped access (F59); no transcoding keeps it simple/cheap | Upload bytes transit the app (CPU/bandwidth on the app tier) rather than going direct-to-bucket; 5-min TTL is a non-zero revocation lag |
| B — Direct browser→bucket presigned PUT upload | Offloads upload bandwidth from the app | App never sees the bytes → cannot sniff content or strip EXIF server-side → violates F58/F61; unacceptable |
| C — Store media as bytea in Postgres | One datastore; transactional with the message | Bloats the DB and backups; no separate serving origin (F59 wants separation); poor fit for 200 MB video; contradicts the separate-origin requirement |

## Consequences
- **Positive:** One storage interface works from laptop (MinIO) to prod with only config changes; the hygiene pipeline (allowlist + sniff + EXIF-strip-or-reject + sanitise + SVG exclusion) is centralised and testable; separate-origin signed URLs keep media out of the app's auth cookie/origin and scope access to current membership; no transcoding keeps cost and complexity down.
- **Negative / trade-offs:** Upload throughput and EXIF-strip CPU land on the app tier — bounded by the 20/min per-user upload limit and size caps, and load-tested before GA. Media access revocation is **bounded but non-zero** (up to the 5-min URL TTL) — a documented privacy boundary (TSD §12). No AV scanning is an accepted risk mitigated only by the allowlist/sniff/EXIF/SVG-exclusion/sanitise controls.
- **Follow-ups:** `infrastructure-engineer` provisions MinIO locally and wires the prod bucket + credentials at deploy; `security-reviewer` reviews the sniff/EXIF/sanitise pipeline and signed-URL scoping in the threat model; `backend-engineer` implements the two-phase upload + orphan-cleanup job; the deployment ADR (ADR-0008) notes the prod provider is chosen alongside the platform since most PaaS options have no built-in object store.

## Compliance / reversibility
Reversible at the provider level (the boto3 abstraction makes swapping S3 providers a config change). Reversing the *topology* (e.g. moving to direct-to-bucket upload) would sacrifice server-side hygiene and is not recommended. Media is PII/sensitive: object keys are opaque, URLs are short-lived and membership-scoped, and no media bytes or signed URLs are logged (R24). No AV scanning is a formally accepted v1 risk.
