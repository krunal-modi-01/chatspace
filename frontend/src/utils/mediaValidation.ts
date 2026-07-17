import type { MediaKind } from '../api/types';
import { formatBytes } from './formatBytes';

/**
 * Client-side, best-effort mirror of the server's authoritative media
 * validation (`backend/app/core/media_validation.py`, F58). This module
 * exists only to give immediate feedback and avoid spending an upload
 * attempt (rate-limited 20/min/user) on a file that will certainly be
 * rejected — the server's response (`413`/`415`) is always the source of
 * truth and is surfaced as-is when it disagrees with this pre-check.
 */

const SIZE_CAP_BYTES_BY_KIND: Record<'image' | 'file' | 'video', number> = {
  image: 10 * 1024 * 1024,
  file: 50 * 1024 * 1024,
  video: 200 * 1024 * 1024,
};

const ALLOWED_IMAGE_CONTENT_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
const ALLOWED_VIDEO_CONTENT_TYPES = new Set(['video/mp4', 'video/webm']);

/** Infers the `kind` multipart field from a `File`'s browser-reported MIME
 * type. Anything not recognized as an allowlisted image/video falls back to
 * `'file'` (the server's `kind=file` path has no fixed allowlist beyond a
 * small denylist of browser-active types — see the server module docstring). */
export function inferMediaKind(contentType: string): MediaKind {
  if (ALLOWED_IMAGE_CONTENT_TYPES.has(contentType)) {
    return 'image';
  }
  if (ALLOWED_VIDEO_CONTENT_TYPES.has(contentType)) {
    return 'video';
  }
  return 'file';
}

function sizeCapBytes(kind: MediaKind): number {
  return SIZE_CAP_BYTES_BY_KIND[kind as 'image' | 'file' | 'video'] ?? SIZE_CAP_BYTES_BY_KIND.file;
}

/** Returns a user-facing message if `file` will certainly be rejected by the
 * server's per-`kind` size cap (F58), or `null` if it passes this
 * best-effort pre-check. Never the sole gate — the server's `413` is always
 * respected as authoritative even if this check passes. */
export function preflightSizeError(file: File, kind: MediaKind): string | null {
  const cap = sizeCapBytes(kind);
  if (file.size > cap) {
    return `"${file.name}" is too large (max ${formatBytes(cap)} for ${kind}).`;
  }
  return null;
}

/** Returns a user-facing message if `image`/`video` `content_type` is
 * outright disallowed (F58 — `image/svg+xml` excluded, non-mp4/webm video
 * excluded), or `null` if it passes this best-effort pre-check. `kind=file`
 * has no fixed client-side allowlist to mirror (server denylist is small and
 * content-sniff-dependent, not worth duplicating here). */
export function preflightTypeError(file: File, kind: MediaKind): string | null {
  if (kind === 'image' && !ALLOWED_IMAGE_CONTENT_TYPES.has(file.type)) {
    return `"${file.name}" is not a supported image type (png, jpeg, gif, webp).`;
  }
  if (kind === 'video' && !ALLOWED_VIDEO_CONTENT_TYPES.has(file.type)) {
    return `"${file.name}" is not a supported video type (mp4, webm).`;
  }
  return null;
}
