import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAuthStore } from '../store/authStore';
import { fetchMediaUrl, uploadMedia, type XhrUploadLike } from './mediaApi';
import { ApiError } from './problem';

const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

/** Minimal fake satisfying `XhrUploadLike`, letting each test script a
 * response and (optionally) fire upload-progress events. */
class FakeXhr implements XhrUploadLike {
  static instances: FakeXhr[] = [];

  status = 0;
  responseText = '';
  headers: Record<string, string> = {};
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
    onprogress: null,
  };
  openArgs: [string, string] | null = null;
  requestHeaders: Record<string, string> = {};
  sentBody: FormData | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open(method: string, url: string): void {
    this.openArgs = [method, url];
  }

  setRequestHeader(name: string, value: string): void {
    this.requestHeaders[name] = value;
  }

  send(body: FormData): void {
    this.sentBody = body;
  }

  getResponseHeader(name: string): string | null {
    return this.headers[name.toLowerCase()] ?? null;
  }

  // --- test helpers ---

  respond(status: number, body: unknown, headers: Record<string, string> = {}): void {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.headers = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    if (!this.headers['content-type']) {
      this.headers['content-type'] = 'application/json';
    }
    this.onload?.();
  }

  progress(loaded: number, total: number): void {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
}

function lastXhr(): FakeXhr {
  const xhr = FakeXhr.instances.at(-1);
  if (!xhr) throw new Error('no FakeXhr instance created');
  return xhr;
}

describe('uploadMedia', () => {
  beforeEach(() => {
    FakeXhr.instances = [];
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function upload(file: File, onProgress?: (fraction: number) => void) {
    return uploadMedia(file, 'image', 'image/png', 'photo.png', {
      createXhr: () => new FakeXhr(),
      onProgress,
    });
  }

  it('POSTs multipart/form-data to /media with the Authorization header and reports progress', async () => {
    const file = new File(['x'.repeat(10)], 'photo.png', { type: 'image/png' });
    const progressValues: number[] = [];

    const promise = upload(file, (fraction) => progressValues.push(fraction));
    const xhr = lastXhr();

    expect(xhr.openArgs?.[0]).toBe('POST');
    expect(xhr.openArgs?.[1]).toContain('/media');
    expect(xhr.requestHeaders.Authorization).toBe(`Bearer ${FIXTURE_ACCESS_TOKEN}`);
    expect(xhr.sentBody).toBeInstanceOf(FormData);
    expect(xhr.sentBody?.get('kind')).toBe('image');
    expect(xhr.sentBody?.get('declared_content_type')).toBe('image/png');
    expect(xhr.sentBody?.get('filename')).toBe('photo.png');

    xhr.progress(5, 10);
    xhr.progress(10, 10);

    xhr.respond(201, {
      media_id: '01J8MEDIA00000000000000000',
      kind: 'image',
      content_type: 'image/png',
      filename: 'photo.png',
      size: 10,
      created_at: '2026-07-02T14:31:07.482Z',
    });

    const result = await promise;
    expect(result.media_id).toBe('01J8MEDIA00000000000000000');
    expect(progressValues).toEqual([0.5, 1]);
  });

  it('surfaces a 413 (size cap) as an ApiError', async () => {
    const file = new File(['x'], 'huge.png', { type: 'image/png' });
    const promise = upload(file);
    lastXhr().respond(413, {
      type: 'https://chatspace.example/problems/media-too-large',
      title: 'Payload too large',
      status: 413,
      detail: 'Upload exceeds the maximum size allowed for this media kind.',
      instance: '/v1/media',
      correlation_id: '01J000EXAMPLE',
    });

    const error = await promise.catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(413);
  });

  it('surfaces a 415 (disallowed type) as an ApiError', async () => {
    const file = new File(['x'], 'bad.svg', { type: 'image/svg+xml' });
    const promise = upload(file);
    lastXhr().respond(415, {
      type: 'https://chatspace.example/problems/media-disallowed',
      title: 'Unsupported media type',
      status: 415,
      detail: 'This media type is not allowed.',
      instance: '/v1/media',
      correlation_id: '01J000EXAMPLE',
    });

    const error = await promise.catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(415);
  });

  it('surfaces a 429 (rate limited) as an ApiError carrying retryAfterSeconds', async () => {
    const file = new File(['x'], 'photo.png', { type: 'image/png' });
    const promise = upload(file);
    lastXhr().respond(
      429,
      {
        type: 'https://chatspace.example/problems/rate-limited',
        title: 'Too many requests',
        status: 429,
        detail: 'Upload rate limit exceeded.',
        instance: '/v1/media',
        correlation_id: '01J000EXAMPLE',
      },
      { 'Retry-After': '30' },
    );

    const error = await promise.catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(429);
    expect((error as ApiError).retryAfterSeconds).toBe(30);
  });
});

describe('fetchMediaUrl', () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('GETs /media/{media_id}/url and returns the presigned URL body', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        url: 'https://storage.example/signed?sig=abc',
        expires_at: '2026-07-02T14:36:07.482Z',
        content_type: 'image/png',
        filename: 'photo.png',
        size: 10,
      }),
    );

    const result = await fetchMediaUrl('01J8MEDIA00000000000000000');

    expect(result.url).toBe('https://storage.example/signed?sig=abc');
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/media/01J8MEDIA00000000000000000/url');
  });

  it('surfaces a 403 (no longer a member) as an ApiError', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          type: 'https://chatspace.example/problems/forbidden',
          title: 'Forbidden',
          status: 403,
          detail: 'Not a current member.',
          instance: '/v1/media/01J8MEDIA00000000000000000/url',
          correlation_id: '01J000EXAMPLE',
        }),
        { status: 403, headers: { 'Content-Type': 'application/problem+json' } },
      ),
    );

    const error = await fetchMediaUrl('01J8MEDIA00000000000000000').catch((err: unknown) => err);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403);
  });
});
