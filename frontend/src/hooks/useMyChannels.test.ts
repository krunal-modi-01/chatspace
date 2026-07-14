import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MyChannelSummary } from '../api/types';

const { listMyChannelsMock } = vi.hoisted(() => ({ listMyChannelsMock: vi.fn() }));

vi.mock('../api/channelsApi', () => ({
  listMyChannels: listMyChannelsMock,
}));

const { useMyChannels } = await import('./useMyChannels');

function channel(overrides: Partial<MyChannelSummary> = {}): MyChannelSummary {
  return {
    id: '01J0CHANNEL0000000000000000',
    name: 'engineering',
    is_private: false,
    created_by: '01J0USER0000000000000000000',
    created_at: '2026-07-01T00:00:00.000Z',
    member_count: 3,
    my_role: 'member',
    ...overrides,
  };
}

describe('useMyChannels', () => {
  beforeEach(() => {
    listMyChannelsMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the caller memberships on mount', async () => {
    listMyChannelsMock.mockResolvedValueOnce({ items: [channel()], next_cursor: null });

    const { result } = renderHook(() => useMyChannels());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channels).toHaveLength(1);
    expect(result.current.channels[0].name).toBe('engineering');
    expect(result.current.error).toBeNull();
  });

  it('follows next_cursor to completion, accumulating every page', async () => {
    listMyChannelsMock
      .mockResolvedValueOnce({ items: [channel({ id: 'c1' })], next_cursor: 'opaque-cursor-1' })
      .mockResolvedValueOnce({ items: [channel({ id: 'c2' })], next_cursor: null });

    const { result } = renderHook(() => useMyChannels());

    await waitFor(() => expect(result.current.channels).toHaveLength(2));
    expect(listMyChannelsMock).toHaveBeenCalledTimes(2);
    expect(listMyChannelsMock).toHaveBeenNthCalledWith(1, {});
    expect(listMyChannelsMock).toHaveBeenNthCalledWith(2, { cursor: 'opaque-cursor-1' });
  });

  it('renders an empty, non-error result when the caller has no memberships', async () => {
    listMyChannelsMock.mockResolvedValueOnce({ items: [], next_cursor: null });

    const { result } = renderHook(() => useMyChannels());

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.channels).toEqual([]);
    expect(result.current.error).toBeNull();
  });

  it('surfaces a fetch failure as error', async () => {
    listMyChannelsMock.mockRejectedValueOnce(new Error('nope'));

    const { result } = renderHook(() => useMyChannels());

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.isLoading).toBe(false);
  });

  it('includes private channels with their own role', async () => {
    listMyChannelsMock.mockResolvedValueOnce({
      items: [channel({ id: 'priv-1', name: 'leadership', is_private: true, my_role: 'admin' })],
      next_cursor: null,
    });

    const { result } = renderHook(() => useMyChannels());

    await waitFor(() => expect(result.current.channels).toHaveLength(1));
    expect(result.current.channels[0]).toMatchObject({ is_private: true, my_role: 'admin' });
  });
});
