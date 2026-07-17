import { create } from 'zustand';
import { listMyChannels } from '../api/channelsApi';
import type { MyChannelSummary } from '../api/types';

interface MyChannelsState {
  channels: MyChannelSummary[];
  isLoading: boolean;
  error: unknown;
  /** The channel id currently rendered by `ChannelPage`, if any — set/cleared
   * by `useChannelRemovalNotice`. Lets `removeChannel` decide, without any
   * router coupling, whether a live `channel.member_removed` event landed on
   * a channel the caller is looking at right now (F75, Flow L step 4a). */
  viewedChannelId: string | null;
  /** Set by `removeChannel` when the removed channel matches
   * `viewedChannelId` — consumed by `useChannelRemovalNotice` to render the
   * "you were removed from this channel" graceful-exit screen. Cleared via
   * `clearRemovedNotice` once acknowledged/navigated away from, or implicitly
   * by `upsertChannel` if the same channel id is live re-added (e.g. removed
   * then immediately re-invited) — otherwise the stale notice would keep
   * blocking the now-valid view even though the channel reappeared. */
  removedChannelId: string | null;
  /** Fetches the caller's full membership set (F73), following
   * `next_cursor` to completion, and replaces `channels` wholesale. Used
   * both for the initial My Channels load and — reusing the same REST
   * catch-up pattern as message history (F55) — on every WS (re)connect,
   * since membership events are at-least-once with **no replay** (contract
   * line 725, Flow L). */
  load: () => Promise<void>;
  /** Idempotent insert-or-replace by channel id (F74) — applied for a live
   * `channel.member_added` event. */
  upsertChannel: (channel: MyChannelSummary) => void;
  /** Idempotent remove by channel id (F75) — applied for a live
   * `channel.member_removed` event. A repeat/unknown id is a no-op. */
  removeChannel: (channelId: string) => void;
  setViewedChannel: (channelId: string | null) => void;
  clearRemovedNotice: () => void;
  /** Restores initial state. Called from `authStore.clearSession()` so this
   * shared, module-scoped store never survives a logout — without this, a
   * subsequent login in the same tab (SPA navigation, no page reload) would
   * briefly (or indefinitely, on a refetch error) render the previous
   * account's private channel names/roles before the new user's `load()`
   * resolves. Membership data is PII-adjacent per CLAUDE.md and must not
   * leak across accounts on a shared/kiosk browser. */
  reset: () => void;
}

const initialState: Pick<
  MyChannelsState,
  'channels' | 'isLoading' | 'error' | 'viewedChannelId' | 'removedChannelId'
> = {
  channels: [],
  isLoading: true,
  error: null,
  viewedChannelId: null,
  removedChannelId: null,
};

export const useMyChannelsStore = create<MyChannelsState>((set, get) => ({
  ...initialState,

  load: async () => {
    set({ isLoading: true, error: null });
    try {
      const collected: MyChannelSummary[] = [];
      let cursor: string | undefined;
      do {
        const page = await listMyChannels(cursor ? { cursor } : {});
        collected.push(...page.items);
        cursor = page.next_cursor ?? undefined;
      } while (cursor);
      set({ channels: collected, isLoading: false, error: null });
    } catch (err) {
      set({ error: err, isLoading: false });
    }
  },

  upsertChannel: (channel) => {
    const { channels, removedChannelId } = get();
    const clearsRemovedNotice = removedChannelId === channel.id ? { removedChannelId: null } : {};
    const index = channels.findIndex((existing) => existing.id === channel.id);
    if (index === -1) {
      set({ channels: [channel, ...channels], ...clearsRemovedNotice });
      return;
    }
    const next = channels.slice();
    next[index] = channel;
    set({ channels: next, ...clearsRemovedNotice });
  },

  removeChannel: (channelId) => {
    const { channels, viewedChannelId } = get();
    set({
      channels: channels.filter((channel) => channel.id !== channelId),
      ...(viewedChannelId === channelId ? { removedChannelId: channelId } : {}),
    });
  },

  setViewedChannel: (channelId) => set({ viewedChannelId: channelId }),

  clearRemovedNotice: () => set({ removedChannelId: null }),

  reset: () => set({ ...initialState }),
}));
