import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MyChannelSummary } from '../api/types';

const { listMyChannelsMock } = vi.hoisted(() => ({ listMyChannelsMock: vi.fn() }));

vi.mock('../api/channelsApi', () => ({
  listMyChannels: listMyChannelsMock,
}));

const { useMyChannelsStore } = await import('./myChannelsStore');

function channel(overrides: Partial<MyChannelSummary> = {}): MyChannelSummary {
  return {
    id: 'chan-1',
    name: 'engineering',
    is_private: false,
    created_by: 'user-1',
    created_at: '2026-07-01T00:00:00.000Z',
    member_count: 3,
    my_role: 'member',
    ...overrides,
  };
}

describe('myChannelsStore', () => {
  beforeEach(() => {
    listMyChannelsMock.mockReset();
    useMyChannelsStore.setState({
      channels: [],
      isLoading: true,
      error: null,
      viewedChannelId: null,
      removedChannelId: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('load', () => {
    it('replaces channels wholesale, following next_cursor to completion', async () => {
      listMyChannelsMock
        .mockResolvedValueOnce({ items: [channel({ id: 'c1' })], next_cursor: 'cursor-1' })
        .mockResolvedValueOnce({ items: [channel({ id: 'c2' })], next_cursor: null });

      await useMyChannelsStore.getState().load();

      expect(listMyChannelsMock).toHaveBeenCalledTimes(2);
      expect(listMyChannelsMock).toHaveBeenNthCalledWith(1, {});
      expect(listMyChannelsMock).toHaveBeenNthCalledWith(2, { cursor: 'cursor-1' });
      expect(useMyChannelsStore.getState().channels.map((c) => c.id)).toEqual(['c1', 'c2']);
      expect(useMyChannelsStore.getState().isLoading).toBe(false);
      expect(useMyChannelsStore.getState().error).toBeNull();
    });

    it('replaces stale channels/error from a prior call on a fresh success', async () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'stale' })], error: new Error('previous') });
      listMyChannelsMock.mockResolvedValueOnce({ items: [channel({ id: 'fresh' })], next_cursor: null });

      await useMyChannelsStore.getState().load();

      expect(useMyChannelsStore.getState().channels.map((c) => c.id)).toEqual(['fresh']);
      expect(useMyChannelsStore.getState().error).toBeNull();
    });

    it('surfaces a fetch failure as error without throwing', async () => {
      listMyChannelsMock.mockRejectedValueOnce(new Error('network down'));

      await useMyChannelsStore.getState().load();

      expect(useMyChannelsStore.getState().error).toBeInstanceOf(Error);
      expect(useMyChannelsStore.getState().isLoading).toBe(false);
    });
  });

  describe('upsertChannel', () => {
    it('inserts a new channel (added live, F74)', () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'existing' })] });

      useMyChannelsStore.getState().upsertChannel(channel({ id: 'new-one', name: 'leadership' }));

      const ids = useMyChannelsStore.getState().channels.map((c) => c.id);
      expect(ids).toContain('new-one');
      expect(ids).toContain('existing');
    });

    it('replaces an existing channel by id in place (idempotent)', () => {
      useMyChannelsStore.setState({
        channels: [channel({ id: 'a', member_count: 1 }), channel({ id: 'b', member_count: 2 })],
      });

      useMyChannelsStore.getState().upsertChannel(channel({ id: 'a', member_count: 99, my_role: 'admin' }));

      const state = useMyChannelsStore.getState();
      expect(state.channels).toHaveLength(2);
      expect(state.channels.find((c) => c.id === 'a')).toMatchObject({ member_count: 99, my_role: 'admin' });
    });

    it('clears a stale removal notice when the same channel id is live re-added (remove-then-re-add)', () => {
      // Regression: viewing channel `a`, removed live (banner raised), then
      // immediately re-added live before navigating away — the banner must
      // not keep blocking the now-valid view.
      useMyChannelsStore.setState({
        channels: [],
        viewedChannelId: 'a',
        removedChannelId: 'a',
      });

      useMyChannelsStore.getState().upsertChannel(channel({ id: 'a' }));

      const state = useMyChannelsStore.getState();
      expect(state.removedChannelId).toBeNull();
      expect(state.channels.map((c) => c.id)).toEqual(['a']);
    });

    it('leaves an unrelated removal notice untouched when a different channel is upserted', () => {
      useMyChannelsStore.setState({ channels: [], removedChannelId: 'other-channel' });

      useMyChannelsStore.getState().upsertChannel(channel({ id: 'a' }));

      expect(useMyChannelsStore.getState().removedChannelId).toBe('other-channel');
    });
  });

  describe('removeChannel', () => {
    it('removes a channel by id (F75)', () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'a' }), channel({ id: 'b' })] });

      useMyChannelsStore.getState().removeChannel('a');

      expect(useMyChannelsStore.getState().channels.map((c) => c.id)).toEqual(['b']);
    });

    it('is a no-op for an id not present (idempotent replay-safe)', () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'a' })] });

      expect(() => useMyChannelsStore.getState().removeChannel('does-not-exist')).not.toThrow();
      expect(useMyChannelsStore.getState().channels).toHaveLength(1);
    });

    it('does not raise a removal notice when the removed channel is not the one being viewed', () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'a' })], viewedChannelId: 'b' });

      useMyChannelsStore.getState().removeChannel('a');

      expect(useMyChannelsStore.getState().removedChannelId).toBeNull();
    });

    it('raises the removal notice when the removed channel is the one currently viewed (F75, Flow L 4a)', () => {
      useMyChannelsStore.setState({ channels: [channel({ id: 'a' })], viewedChannelId: 'a' });

      useMyChannelsStore.getState().removeChannel('a');

      expect(useMyChannelsStore.getState().removedChannelId).toBe('a');
    });
  });

  describe('viewed channel / removal notice bookkeeping', () => {
    it('setViewedChannel records the currently-open channel', () => {
      useMyChannelsStore.getState().setViewedChannel('chan-9');
      expect(useMyChannelsStore.getState().viewedChannelId).toBe('chan-9');

      useMyChannelsStore.getState().setViewedChannel(null);
      expect(useMyChannelsStore.getState().viewedChannelId).toBeNull();
    });

    it('clearRemovedNotice clears the removal flag', () => {
      useMyChannelsStore.setState({ removedChannelId: 'chan-9' });

      useMyChannelsStore.getState().clearRemovedNotice();

      expect(useMyChannelsStore.getState().removedChannelId).toBeNull();
    });
  });

  describe('reset', () => {
    it('restores initial state, wiping any previous account’s channels/role data', () => {
      useMyChannelsStore.setState({
        channels: [channel({ id: 'private-channel', is_private: true, my_role: 'admin' })],
        isLoading: false,
        error: new Error('stale'),
        viewedChannelId: 'private-channel',
        removedChannelId: 'private-channel',
      });

      useMyChannelsStore.getState().reset();

      expect(useMyChannelsStore.getState()).toMatchObject({
        channels: [],
        isLoading: true,
        error: null,
        viewedChannelId: null,
        removedChannelId: null,
      });
    });
  });
});
