import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/problem';

const { uploadMediaMock, generateClientIdMock } = vi.hoisted(() => ({
  uploadMediaMock: vi.fn(),
  generateClientIdMock: vi.fn(),
}));

vi.mock('../api/mediaApi', () => ({
  uploadMedia: uploadMediaMock,
}));

vi.mock('../utils/id', () => ({
  generateClientId: generateClientIdMock,
}));

const { useMediaUploads } = await import('./useMediaUploads');

function makeFile(name: string, type: string, size = 100): File {
  return new File([new Uint8Array(size)], name, { type });
}

function uploadResponse(overrides: Partial<{ media_id: string }> = {}) {
  return {
    media_id: '01J8MEDIA00000000000000000',
    kind: 'image',
    content_type: 'image/png',
    filename: 'photo.png',
    size: 100,
    created_at: '2026-07-02T14:31:07.482Z',
    ...overrides,
  };
}

describe('useMediaUploads', () => {
  let idCounter = 0;

  beforeEach(() => {
    idCounter = 0;
    generateClientIdMock.mockImplementation(() => `client-id-${(idCounter += 1)}`);
    uploadMediaMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('uploads an added file and exposes it as done with its media_id once resolved', async () => {
    let resolveUpload!: (value: ReturnType<typeof uploadResponse>) => void;
    uploadMediaMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );

    const { result } = renderHook(() => useMediaUploads());

    act(() => {
      result.current.addFiles([makeFile('photo.png', 'image/png')]);
    });

    expect(result.current.attachments).toHaveLength(1);
    expect(result.current.attachments[0].status).toBe('uploading');
    expect(result.current.isUploading).toBe(true);
    expect(result.current.readyMediaIds).toEqual([]);

    await act(async () => {
      resolveUpload(uploadResponse());
    });

    await waitFor(() => expect(result.current.attachments[0].status).toBe('done'));
    expect(result.current.isUploading).toBe(false);
    expect(result.current.readyMediaIds).toEqual(['01J8MEDIA00000000000000000']);
  });

  it('reports live progress via onProgress', async () => {
    let capturedOnProgress!: (fraction: number) => void;
    uploadMediaMock.mockImplementationOnce((_file, _kind, _contentType, _filename, options) => {
      capturedOnProgress = options.onProgress;
      return new Promise(() => {
        // never resolves in this test
      });
    });

    const { result } = renderHook(() => useMediaUploads());
    act(() => {
      result.current.addFiles([makeFile('photo.png', 'image/png')]);
    });

    act(() => {
      capturedOnProgress(0.42);
    });

    await waitFor(() => expect(result.current.attachments[0].progress).toBeCloseTo(0.42));
  });

  it('rejects an oversized file client-side without calling uploadMedia', () => {
    const { result } = renderHook(() => useMediaUploads());

    act(() => {
      result.current.addFiles([makeFile('huge.png', 'image/png', 11 * 1024 * 1024)]);
    });

    expect(result.current.attachments[0].status).toBe('error');
    expect(result.current.attachments[0].error).toMatch(/too large/i);
    expect(result.current.hasError).toBe(true);
    expect(uploadMediaMock).not.toHaveBeenCalled();
  });

  it('captures a server error (e.g. 415) with retryAfterSeconds when present, and retryAttachment re-uploads', async () => {
    uploadMediaMock.mockRejectedValueOnce(
      new ApiError(
        {
          type: 'https://chatspace.example/problems/rate-limited',
          title: 'Too many requests',
          status: 429,
          detail: 'Upload rate limit exceeded.',
          instance: '/v1/media',
          correlation_id: '01J000EXAMPLE',
        },
        12,
      ),
    );

    const { result } = renderHook(() => useMediaUploads());
    act(() => {
      result.current.addFiles([makeFile('photo.png', 'image/png')]);
    });

    await waitFor(() => expect(result.current.attachments[0].status).toBe('error'));
    expect(result.current.attachments[0].retryAfterSeconds).toBe(12);
    expect(result.current.hasError).toBe(true);

    uploadMediaMock.mockResolvedValueOnce(uploadResponse());
    act(() => {
      result.current.retryAttachment(result.current.attachments[0].id);
    });

    await waitFor(() => expect(result.current.attachments[0].status).toBe('done'));
    expect(result.current.hasError).toBe(false);
  });

  it('removeAttachment drops the attachment entirely', async () => {
    uploadMediaMock.mockResolvedValueOnce(uploadResponse());
    const { result } = renderHook(() => useMediaUploads());

    act(() => {
      result.current.addFiles([makeFile('photo.png', 'image/png')]);
    });
    await waitFor(() => expect(result.current.attachments[0].status).toBe('done'));

    act(() => {
      result.current.removeAttachment(result.current.attachments[0].id);
    });

    expect(result.current.attachments).toHaveLength(0);
    expect(result.current.readyMediaIds).toEqual([]);
  });

  it('reset clears every attachment', async () => {
    uploadMediaMock.mockResolvedValueOnce(uploadResponse());
    const { result } = renderHook(() => useMediaUploads());

    act(() => {
      result.current.addFiles([makeFile('photo.png', 'image/png')]);
    });
    await waitFor(() => expect(result.current.attachments[0].status).toBe('done'));

    act(() => {
      result.current.reset();
    });

    expect(result.current.attachments).toHaveLength(0);
  });
});
