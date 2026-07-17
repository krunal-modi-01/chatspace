import { useEffect } from 'react';
import { useMyChannelsStore } from '../store/myChannelsStore';

export interface ChannelRemovalNotice {
  /** True once a live `channel.member_removed` event has landed for this
   * exact channel id while it was the currently-viewed channel (F75). The
   * caller (`ChannelPage`) should render a graceful exit screen instead of
   * its normal content when this is true. */
  wasRemoved: boolean;
  /** Clears the notice — call once the user has acknowledged it (e.g.
   * navigating back to the channel list) so a later re-add doesn't leave a
   * stale "removed" screen behind. */
  dismiss: () => void;
}

/**
 * Registers `channelId` as the currently-open channel view with the shared
 * `myChannelsStore` (T51) for the lifetime of the calling component, and
 * reports whether a `channel.member_removed` event has arrived for it while
 * open — the client-side half of Flow L step 4a / F75's "exit any open
 * view of it gracefully" requirement. The event itself is handled by the
 * app-level `useChannelMembershipSocket`, which has no knowledge of what's
 * currently rendered; this hook is the other end of that handoff, done via
 * shared store state rather than route-path parsing so it stays correct
 * regardless of how `ChannelPage` is routed.
 */
export function useChannelRemovalNotice(channelId: string): ChannelRemovalNotice {
  const removedChannelId = useMyChannelsStore((state) => state.removedChannelId);

  useEffect(() => {
    useMyChannelsStore.getState().setViewedChannel(channelId);
    return () => {
      const state = useMyChannelsStore.getState();
      if (state.viewedChannelId === channelId) {
        state.setViewedChannel(null);
      }
      if (state.removedChannelId === channelId) {
        state.clearRemovedNotice();
      }
    };
  }, [channelId]);

  return {
    wasRemoved: removedChannelId === channelId,
    dismiss: () => useMyChannelsStore.getState().clearRemovedNotice(),
  };
}
