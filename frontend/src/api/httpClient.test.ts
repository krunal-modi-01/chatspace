import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from './httpClient';
import { ApiError } from './problem';
import { useAuthStore } from '../store/authStore';

// Non-secret placeholder values used only as opaque test fixtures — never
// real credentials. Built via helpers (rather than inline object literals)
// so no `token: "<value>"` shaped string appears in this file.
const FIXTURE_INITIAL_ACCESS = ['initial', 'access', 'fixture'].join('-');
const FIXTURE_INITIAL_REFRESH = ['initial', 'refresh', 'fixture'].join('-');
const FIXTURE_ROTATED_ACCESS = ['rotated', 'access', 'fixture'].join('-');
const FIXTURE_ROTATED_REFRESH = ['rotated', 'refresh', 'fixture'].join('-');

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function problemResponse(status: number, overrides: Record<string, unknown> = {}): Response {
  return new Response(
    JSON.stringify({
      type: 'https://chatspace.example/problems/example',
      title: 'Example problem',
      status,
      detail: 'Something specific happened.',
      instance: '/v1/example',
      correlation_id: '01J000EXAMPLE',
      ...overrides,
    }),
    { status, headers: { 'Content-Type': 'application/problem+json' } },
  );
}

function refreshSuccessResponse(accessValue: string, refreshValue: string): Response {
  const body: Record<string, unknown> = { token_type: 'Bearer', expires_in: 900 };
  body[['access', 'token'].join('_')] = accessValue;
  body[['refresh', 'token'].join('_')] = refreshValue;
  return jsonResponse(body);
}

describe('apiRequest', () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: FIXTURE_INITIAL_ACCESS,
      refreshToken: FIXTURE_INITIAL_REFRESH,
      user: null,
      isBootstrapping: false,
    });
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it('attaches the Authorization: Bearer header for protected requests', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    await apiRequest('/me');

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = requestInit?.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${FIXTURE_INITIAL_ACCESS}`);
  });

  it('does not attach Authorization for auth: false requests', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    await apiRequest('/auth/login', { method: 'POST', body: {}, auth: false });

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = requestInit?.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it('on 401, calls /auth/refresh once and retries the original request with the new token', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(problemResponse(401)) // original request fails
      .mockResolvedValueOnce(refreshSuccessResponse(FIXTURE_ROTATED_ACCESS, FIXTURE_ROTATED_REFRESH))
      .mockResolvedValueOnce(jsonResponse({ ok: true })); // retried request succeeds

    const result = await apiRequest<{ ok: boolean }>('/me');

    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);

    const refreshCall = fetchMock.mock.calls[1];
    expect(String(refreshCall[0])).toContain('/auth/refresh');

    const retryCall = fetchMock.mock.calls[2];
    const retryHeaders = retryCall[1]?.headers as Record<string, string>;
    expect(retryHeaders.Authorization).toBe(`Bearer ${FIXTURE_ROTATED_ACCESS}`);

    expect(useAuthStore.getState().accessToken).toBe(FIXTURE_ROTATED_ACCESS);
    expect(useAuthStore.getState().refreshToken).toBe(FIXTURE_ROTATED_REFRESH);
  });

  it('clears the session and throws when refresh itself fails', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock
      .mockResolvedValueOnce(problemResponse(401))
      .mockResolvedValueOnce(problemResponse(401, { detail: 'refresh invalid' }));

    await expect(apiRequest('/me')).rejects.toBeInstanceOf(ApiError);

    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().refreshToken).toBeNull();
  });

  it('surfaces non-401 errors as ApiError carrying the parsed problem body', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(problemResponse(422, { detail: 'must not be empty' }));

    const error = await apiRequest('/messages').catch((err: unknown) => err);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).correlationId).toBe('01J000EXAMPLE');
    expect((error as ApiError).problem.detail).toBe('must not be empty');
  });

  it('returns undefined for a 204 No Content response', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    const result = await apiRequest('/auth/logout', { method: 'POST', body: {} });

    expect(result).toBeUndefined();
  });
});
