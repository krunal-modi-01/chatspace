import { env } from '../config/env';
import { authStoreApi } from '../store/authStore';
import { ApiError, networkErrorProblem, parseErrorResponse } from './problem';
import type { RefreshRequest, RefreshResponse } from './types';

const REFRESH_PATH = '/auth/refresh';

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  /** Set false for the public auth endpoints that must not (and, pre-login,
   * cannot) carry a Bearer token. Defaults to true. */
  auth?: boolean;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

/** Single-flight in-flight refresh promise so concurrent 401s trigger only
 * one `/auth/refresh` call, not one per failed request. */
let refreshInFlight: Promise<string> | null = null;

async function performRefresh(): Promise<string> {
  const { refreshToken } = authStoreApi.getState();
  if (!refreshToken) {
    throw new ApiError({
      type: 'https://chatspace.example/problems/unauthenticated',
      title: 'Not authenticated',
      status: 401,
      detail: 'No refresh token available.',
      instance: REFRESH_PATH,
      correlation_id: 'unknown',
    });
  }

  const response = await fetch(`${env.apiBaseUrl}${REFRESH_PATH}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken } satisfies RefreshRequest),
  });

  if (!response.ok) {
    authStoreApi.getState().clearSession();
    throw new ApiError(await parseErrorResponse(response, REFRESH_PATH));
  }

  const data = (await response.json()) as RefreshResponse;
  authStoreApi.getState().setSession({
    accessToken: data.access_token,
    // The refresh token may be rotated — always persist what came back.
    refreshToken: data.refresh_token,
  });
  return data.access_token;
}

/**
 * Exported (in addition to the internal 401-retry use above) so other
 * long-lived clients — namely the WS client's 4402/token-expired close-code
 * handling — can force a refresh through the same single-flight guard
 * rather than duplicating the refresh call/rotation logic.
 */
export function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = performRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function doFetch(path: string, options: RequestOptions, accessToken: string | null): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: 'application/json, application/problem+json',
    ...options.headers,
  };
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (options.auth !== false && accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  return fetch(`${env.apiBaseUrl}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
}

/**
 * Typed REST client. Injects `Authorization: Bearer` for protected requests,
 * transparently retries once via `/v1/auth/refresh` on a 401, and surfaces
 * every non-2xx response as an `ApiError` carrying a parsed problem+json body.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const isRefreshCall = path === REFRESH_PATH;
  let response: Response;

  try {
    response = await doFetch(path, options, authStoreApi.getState().accessToken);
  } catch {
    throw new ApiError(networkErrorProblem(path));
  }

  if (response.status === 401 && options.auth !== false && !isRefreshCall) {
    // If refreshAccessToken() throws (refresh invalid/revoked/expired), the
    // session was already cleared inside performRefresh() and the error
    // propagates to the caller as-is; route guards (ProtectedRoute) will
    // redirect to /login on next render.
    const newAccessToken = await refreshAccessToken();
    try {
      response = await doFetch(path, options, newAccessToken);
    } catch {
      throw new ApiError(networkErrorProblem(path));
    }
  }

  if (!response.ok) {
    throw new ApiError(await parseErrorResponse(response, path));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
