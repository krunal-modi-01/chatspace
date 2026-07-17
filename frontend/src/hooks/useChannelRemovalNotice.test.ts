import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useChannelRemovalNotice } from './useChannelRemovalNotice';
import { useMyChannelsStore } from '../store/myChannelsStore';

describe('useChannelRemovalNotice', () => {
  beforeEach(() => {
    useMyChannelsStore.setState({
      channels: [],
      isLoading: false,
      error: null,
      viewedChannelId: null,
      removedChannelId: null,
    });
  });

  afterEach(() => {
    useMyChannelsStore.setState({ viewedChannelId: null, removedChannelId: null });
  });

  it('registers the channel as currently viewed on mount', () => {
    renderHook(() => useChannelRemovalNotice('chan-1'));

    expect(useMyChannelsStore.getState().viewedChannelId).toBe('chan-1');
  });

  it('reports wasRemoved: false while no removal notice is raised', () => {
    const { result } = renderHook(() => useChannelRemovalNotice('chan-1'));

    expect(result.current.wasRemoved).toBe(false);
  });

  it('reports wasRemoved: true once the store raises a removal notice for this channel', () => {
    const { result } = renderHook(() => useChannelRemovalNotice('chan-1'));

    act(() => {
      useMyChannelsStore.getState().removeChannel('chan-1');
    });

    expect(result.current.wasRemoved).toBe(true);
  });

  it('does not report wasRemoved for a different channel’s removal', () => {
    const { result } = renderHook(() => useChannelRemovalNotice('chan-1'));

    act(() => {
      useMyChannelsStore.setState({ viewedChannelId: 'chan-2' });
      useMyChannelsStore.getState().removeChannel('chan-2');
    });

    expect(result.current.wasRemoved).toBe(false);
  });

  it('dismiss() clears the removal notice', () => {
    const { result } = renderHook(() => useChannelRemovalNotice('chan-1'));

    act(() => {
      useMyChannelsStore.getState().removeChannel('chan-1');
    });
    expect(result.current.wasRemoved).toBe(true);

    act(() => {
      result.current.dismiss();
    });

    expect(result.current.wasRemoved).toBe(false);
    expect(useMyChannelsStore.getState().removedChannelId).toBeNull();
  });

  it('clears viewedChannelId (and a matching removal notice) on unmount', () => {
    const { unmount } = renderHook(() => useChannelRemovalNotice('chan-1'));
    act(() => {
      useMyChannelsStore.getState().removeChannel('chan-1');
    });
    expect(useMyChannelsStore.getState().viewedChannelId).toBe('chan-1');

    unmount();

    expect(useMyChannelsStore.getState().viewedChannelId).toBeNull();
    expect(useMyChannelsStore.getState().removedChannelId).toBeNull();
  });
});
