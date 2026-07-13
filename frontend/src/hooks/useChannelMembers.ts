import { useEffect, useState } from 'react';
import { fetchChannelMembers } from '../api/channelsApi';
import type { ChannelMemberSummary } from '../api/types';

const PAGE_LIMIT = 100;
/** Safety cap on pages walked when hydrating the full member list, so an
 * unexpectedly large channel can't spin this into an unbounded fetch loop
 * (same defensive posture as `ws/catchUp.ts`'s `maxPages`). */
const MAX_PAGES = 20;

export interface ChannelMembersState {
  /** Identity source for message author badges, keyed by `user_id`. */
  membersById: ReadonlyMap<string, ChannelMemberSummary>;
  isLoading: boolean;
  error: unknown;
}

/**
 * Loads a channel's member list (T31's endpoint) once per channel — the
 * only identity source in T32 scope for resolving a message's `sender_id`
 * to a display name/initials/avatar. Read-only consumption; membership
 * management UI itself is T31's scope, not built here.
 */
export function useChannelMembers(channelId: string | null): ChannelMembersState {
  const [membersById, setMembersById] = useState<ReadonlyMap<string, ChannelMemberSummary>>(new Map());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setMembersById(new Map());
    setError(null);

    if (channelId === null) {
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);

    async function load(): Promise<void> {
      try {
        const collected = new Map<string, ChannelMemberSummary>();
        let offset = 0;
        for (let page = 0; page < MAX_PAGES; page += 1) {
          const result = await fetchChannelMembers(channelId as string, { limit: PAGE_LIMIT, offset });
          for (const member of result.items) {
            collected.set(member.user_id, member);
          }
          offset += result.items.length;
          if (result.items.length === 0 || collected.size >= result.total) {
            break;
          }
        }
        if (!cancelled) {
          setMembersById(collected);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [channelId]);

  return { membersById, isLoading, error };
}
