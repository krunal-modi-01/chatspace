import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/problem';
import type { MessageMedia } from '../../api/types';
import { MediaAttachment } from './MediaAttachment';

const { fetchMediaUrlMock } = vi.hoisted(() => ({
  fetchMediaUrlMock: vi.fn(),
}));

vi.mock('../../api/mediaApi', () => ({
  fetchMediaUrl: fetchMediaUrlMock,
}));

function urlResponse(overrides: Partial<{ url: string; content_type: string }> = {}) {
  return {
    url: 'https://storage.example/signed?sig=abc',
    expires_at: '2026-07-02T14:36:07.482Z',
    content_type: 'image/png',
    filename: 'photo.png',
    size: 2048,
    ...overrides,
  };
}

function media(overrides: Partial<MessageMedia> = {}): MessageMedia {
  return {
    media_id: '01J8MEDIA00000000000000000',
    kind: 'image',
    filename: 'photo.png',
    size: 2048,
    ...overrides,
  };
}

describe('MediaAttachment', () => {
  afterEach(() => {
    fetchMediaUrlMock.mockReset();
  });

  it('shows a loading state, then fetches the presigned URL and renders an image inline', async () => {
    fetchMediaUrlMock.mockResolvedValueOnce(urlResponse());
    render(<MediaAttachment media={media()} />);

    expect(screen.getByRole('status')).toHaveTextContent(/loading photo.png/i);

    const img = await screen.findByRole('img', { name: 'photo.png' });
    expect(img).toHaveAttribute('src', 'https://storage.example/signed?sig=abc');
    expect(fetchMediaUrlMock).toHaveBeenCalledWith('01J8MEDIA00000000000000000');
  });

  it('renders a download affordance with filename+size for a non-inline kind', async () => {
    fetchMediaUrlMock.mockResolvedValueOnce(urlResponse({ content_type: 'application/pdf' }));
    render(<MediaAttachment media={media({ kind: 'file', filename: 'report.pdf', size: 1024 })} />);

    const link = await screen.findByRole('link', { name: /download report.pdf/i });
    expect(link).toHaveAttribute('href', 'https://storage.example/signed?sig=abc');
    expect(link).toHaveAttribute('download', 'report.pdf');
    expect(screen.getByText('report.pdf')).toBeInTheDocument();
    expect(screen.getByText('(1.0 KB)')).toBeInTheDocument();
  });

  it('falls back to a download affordance if an image fails to decode', async () => {
    fetchMediaUrlMock.mockResolvedValueOnce(urlResponse());
    render(<MediaAttachment media={media()} />);

    const img = await screen.findByRole('img', { name: 'photo.png' });
    img.dispatchEvent(new Event('error'));

    await waitFor(() => expect(screen.getByRole('link', { name: /download photo.png/i })).toBeInTheDocument());
  });

  it('shows an inline error when the presigned URL fetch fails (e.g. 403)', async () => {
    fetchMediaUrlMock.mockRejectedValueOnce(
      new ApiError({
        type: 'https://chatspace.example/problems/forbidden',
        title: 'Forbidden',
        status: 403,
        detail: 'Not a current member.',
        instance: '/v1/media/01J8MEDIA00000000000000000/url',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    render(<MediaAttachment media={media()} />);

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/not a current member/i));
  });
});
