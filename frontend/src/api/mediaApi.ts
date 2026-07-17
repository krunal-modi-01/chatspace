import { env } from '../config/env';
import { authStoreApi } from '../store/authStore';
import { apiRequest, refreshAccessToken } from './httpClient';
import { ApiError, networkErrorProblem, parseErrorResponse } from './problem';
import type { MediaKind, MediaUploadResponse, MediaUrlResponse } from './types';

const UPLOAD_PATH = '/media';

/**
 * Minimal surface of `XMLHttpRequest` this module depends on — narrowed to
 * exactly what a single `multipart/form-data` POST with upload-progress
 * reporting needs, and substitutable in tests (the same dependency-injection
 * pattern `ws/socketClient.ts`'s `WebSocketLike` uses for `WebSocket`). The
 * real browser `XMLHttpRequest` satisfies this structurally, so no adapter is
 * needed outside tests. `fetch` is not used here because it has no
 * cross-browser upload-progress API.
 */
export interface XhrUploadLike {
  open(method: string, url: string): void;
  setRequestHeader(name: string, value: string): void;
  send(body: FormData): void;
  readonly status: number;
  readonly responseText: string;
  getResponseHeader(name: string): string | null;
  onload: (() => void) | null;
  onerror: (() => void) | null;
  upload: {
    onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null;
  };
}

function defaultXhrFactory(): XhrUploadLike {
  return new XMLHttpRequest() as unknown as XhrUploadLike;
}

export interface UploadMediaOptions {
  /** Called with a fraction in `[0, 1]` on each upload-progress tick. Only
   * fires when the browser reports `lengthComputable` (true for
   * `FormData`/`File` bodies in every evergreen browser). */
  onProgress?: (fraction: number) => void;
  /** Injected for tests; defaults to the real `XMLHttpRequest`. */
  createXhr?: () => XhrUploadLike;
}

function buildFormData(file: File | Blob, kind: MediaKind, declaredContentType: string, filename: string): FormData {
  const formData = new FormData();
  formData.append('file', file, filename);
  formData.append('declared_content_type', declaredContentType);
  formData.append('kind', kind);
  formData.append('filename', filename);
  return formData;
}

function sendOnce(formData: FormData, accessToken: string | null, options: UploadMediaOptions): Promise<XhrUploadLike> {
  return new Promise((resolve, reject) => {
    const xhr = (options.createXhr ?? defaultXhrFactory)();
    xhr.open('POST', `${env.apiBaseUrl}${UPLOAD_PATH}`);
    xhr.setRequestHeader('Accept', 'application/json, application/problem+json');
    if (accessToken) {
      xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    }
    if (options.onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && event.total > 0) {
          options.onProgress?.(event.loaded / event.total);
        }
      };
    }
    xhr.onerror = () => reject(new Error('network-error'));
    xhr.onload = () => resolve(xhr);
    xhr.send(formData);
  });
}

async function toApiError(xhr: XhrUploadLike): Promise<ApiError> {
  const contentType = xhr.getResponseHeader('content-type') ?? '';
  const response = new Response(xhr.responseText, {
    status: xhr.status,
    headers: contentType ? { 'content-type': contentType } : undefined,
  });
  const problem = await parseErrorResponse(response, UPLOAD_PATH);
  const retryAfterHeader = xhr.getResponseHeader('Retry-After');
  const retryAfterSeconds = retryAfterHeader !== null ? Number(retryAfterHeader) : undefined;
  return new ApiError(
    problem,
    retryAfterSeconds !== undefined && Number.isFinite(retryAfterSeconds) ? retryAfterSeconds : undefined,
  );
}

/**
 * Protected — uploads one file via phase 1 of the frozen two-phase media
 * contract (`POST /v1/media`, `multipart/form-data`: `file`,
 * `declared_content_type`, `kind`, `filename`). Reports upload progress via
 * `options.onProgress`. Surfaces `400` (malformed/missing parts), `413`
 * (over the per-`kind` size cap, F58), `415` (disallowed type / sniff
 * mismatch / EXIF-strip failure, F58/F61), and `429` (+ `Retry-After`,
 * upload rate limit, 20/min/user) as `ApiError` — same shape every other
 * endpoint uses. Retries once on `401` through the shared single-flight
 * refresh (`httpClient.refreshAccessToken`), matching `apiRequestWithStatus`.
 */
export async function uploadMedia(
  file: File | Blob,
  kind: MediaKind,
  declaredContentType: string,
  filename: string,
  options: UploadMediaOptions = {},
): Promise<MediaUploadResponse> {
  const formData = buildFormData(file, kind, declaredContentType, filename);

  let xhr: XhrUploadLike;
  try {
    xhr = await sendOnce(formData, authStoreApi.getState().accessToken, options);
  } catch {
    throw new ApiError(networkErrorProblem(UPLOAD_PATH));
  }

  if (xhr.status === 401) {
    const newAccessToken = await refreshAccessToken();
    try {
      xhr = await sendOnce(formData, newAccessToken, options);
    } catch {
      throw new ApiError(networkErrorProblem(UPLOAD_PATH));
    }
  }

  if (xhr.status < 200 || xhr.status >= 300) {
    throw await toApiError(xhr);
  }

  return JSON.parse(xhr.responseText) as MediaUploadResponse;
}

/**
 * Protected, idempotent — issues a fresh, short-lived (5 min) presigned GET
 * URL for `mediaId` (phase 2 of the two-phase media flow). MUST be called at
 * fetch/render time and never cached beyond the current render (frozen
 * contract: "URL short-lived; never logged"). `403` when the caller is no
 * longer a member/participant of the parent conversation; `404` uniform for
 * unknown/unassociated media.
 */
export function fetchMediaUrl(mediaId: string): Promise<MediaUrlResponse> {
  return apiRequest<MediaUrlResponse>(`/media/${encodeURIComponent(mediaId)}/url`, { method: 'GET' });
}
