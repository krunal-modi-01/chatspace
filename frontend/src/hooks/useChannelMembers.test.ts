import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChannelMemberSummary } from '../api/types';

const { fetchChannelMembersMock } = vi.hoisted(() => ({ fetchChannelMembersMock: vi.fn() }));

vi.mock('../api/channelsApi', () => ({
  fetchChannelMembers: fetchChannelMembersMock,
}));

const { useChannelMembers } = await import('./useChannelMembers');

function member(overrides: Partial<ChannelMemberSummary> = {}): ChannelMemberSummary {
  return {
    user_id: '01J0USER0000000000000000000',
    username: 'ada',
    first_name: 'Ada',
    last_name: 'Lovelace',
    avatar_url: null,
    role: 'member',
    joined_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  };
}

describe('useChannelMembers', () => {
  beforeEach(() => {
    fetchChannelMembersMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns an empty map and does not fetch when channelId is null', () => {
    const { result } = renderHook(() => useChannelMembers(null));
    expect(result.current.membersById.size).toBe(0);
    expect(fetchChannelMembersMock).not.toHaveBeenCalled();
  });

  it('loads members into a map keyed by user_id', async () => {
    fetchChannelMembersMock.mockResolvedValueOnce({ items: [member()], total: 1 });

    const { result } = renderHook(() => useChannelMembers('01J0CHANNEL0000000000000000'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.membersById.get('01J0USER0000000000000000000')?.username).toBe('ada');
  });

  it('pages through additional offsets until total is reached', async () => {
    fetchChannelMembersMock
      .mockResolvedValueOnce({ items: [member({ user_id: 'u1' })], total: 2 })
      .mockResolvedValueOnce({ items: [member({ user_id: 'u2' })], total: 2 });

    const { result } = renderHook(() => useChannelMembers('01J0CHANNEL0000000000000000'));

    await waitFor(() => expect(result.current.membersById.size).toBe(2));
    expect(fetchChannelMembersMock).toHaveBeenCalledTimes(2);
  });

  it('surfaces a fetch failure as error', async () => {
    fetchChannelMembersMock.mockRejectedValueOnce(new Error('nope'));

    const { result } = renderHook(() => useChannelMembers('01J0CHANNEL0000000000000000'));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.isLoading).toBe(false);
  });
});
