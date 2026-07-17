import { useEffect } from 'react';
import { useMyChannelsStore } from '../store/myChannelsStore';

/**
 * Drives the "My Channels" navigation list (T50): every channel — public
 * and private — the caller belongs to, via the cursor-paginated
 * `GET /v1/channels` (F73). Follows the `useChannelBrowse` template (load on
 * mount, expose `isLoading`/error/reload), but unlike a browse/admin table
 * this is a navigation surface, not a paged list view — the contract notes
 * "a small membership set typically fits one page", so rather than
 * exposing Prev/Next controls in the nav, this hook follows `next_cursor`
 * to completion and exposes the full membership set at once.
 *
 * Backed by the shared `myChannelsStore` (T51) rather than local state, so
 * this list stays in sync with the app-level `channel.member_added`/
 * `channel.member_removed` WS listener (`useChannelMembershipSocket`) — a
 * channel added/removed from another tab or by an admin updates every
 * mounted consumer of this hook live, without a page refresh.
 */
export function useMyChannels() {
  const channels = useMyChannelsStore((state) => state.channels);
  const isLoading = useMyChannelsStore((state) => state.isLoading);
  const error = useMyChannelsStore((state) => state.error);
  const load = useMyChannelsStore((state) => state.load);

  useEffect(() => {
    load();
    // `load` is a stable store action reference (zustand), so this still
    // runs exactly once per mount, matching the pre-T51 local-state
    // behavior.
  }, [load]);

  return {
    channels,
    isLoading,
    error,
    reload: load,
  };
}
