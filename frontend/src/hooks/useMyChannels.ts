import { useCallback, useEffect, useState } from 'react';
import { listMyChannels } from '../api/channelsApi';
import type { MyChannelSummary } from '../api/types';

/**
 * Drives the "My Channels" navigation list (T50): every channel — public
 * and private — the caller belongs to, via the cursor-paginated
 * `GET /v1/channels` (F73). Follows the `useChannelBrowse` template (load on
 * mount, expose `isLoading`/error/reload), but unlike a browse/admin table
 * this is a navigation surface, not a paged list view — the contract notes
 * "a small membership set typically fits one page", so rather than
 * exposing Prev/Next controls in the nav, this hook follows `next_cursor`
 * to completion and exposes the full membership set at once.
 */
export function useMyChannels() {
  const [channels, setChannels] = useState<MyChannelSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const collected: MyChannelSummary[] = [];
      let cursor: string | undefined;
      do {
        const page = await listMyChannels(cursor ? { cursor } : {});
        collected.push(...page.items);
        cursor = page.next_cursor ?? undefined;
      } while (cursor);
      setChannels(collected);
    } catch (err) {
      setError(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return {
    channels,
    isLoading,
    error,
    reload: load,
  };
}
