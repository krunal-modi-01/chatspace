import { useCallback, useEffect, useState } from 'react';
import { createChannel, joinChannel, listPublicChannels } from '../api/channelsApi';
import type { CreateChannelResponse, PublicChannelSummary } from '../api/types';

/** Mirrors the DB CHECK constraint on `channels.name` (R36):
 * `^[A-Za-z0-9 _-]{1,80}$`. */
const CHANNEL_NAME_PATTERN = /^[A-Za-z0-9 _-]{1,80}$/;

/** Offset page size — the frozen contract fixes both the default AND the
 * server-enforced maximum at 50 for `GET /channels/public`. */
export const PUBLIC_CHANNELS_PAGE_SIZE = 50;

/**
 * Drives the channel browse/create screen: the create-channel form (with
 * client-side name validation mirroring the DB CHECK) plus the
 * offset-paginated public-channel browse + join list. Kept out of the page
 * component's JSX per the "no inline business logic in JSX" convention.
 */
export function useChannelBrowse() {
  const [name, setName] = useState('');
  const [isPrivate, setIsPrivate] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<unknown>(null);
  const [isCreating, setIsCreating] = useState(false);

  const [channels, setChannels] = useState<PublicChannelSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [listError, setListError] = useState<unknown>(null);

  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [joinError, setJoinError] = useState<unknown>(null);

  const load = useCallback(async (nextOffset: number) => {
    setIsLoading(true);
    setListError(null);
    try {
      const response = await listPublicChannels({ limit: PUBLIC_CHANNELS_PAGE_SIZE, offset: nextOffset });
      setChannels(response.items);
      setTotal(response.total);
      setOffset(response.offset);
    } catch (err) {
      setListError(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load(0);
  }, [load]);

  const hasNextPage = offset + PUBLIC_CHANNELS_PAGE_SIZE < total;
  const hasPreviousPage = offset > 0;

  const nextPage = useCallback(() => {
    if (hasNextPage) {
      load(offset + PUBLIC_CHANNELS_PAGE_SIZE);
    }
  }, [hasNextPage, load, offset]);

  const previousPage = useCallback(() => {
    if (hasPreviousPage) {
      load(Math.max(0, offset - PUBLIC_CHANNELS_PAGE_SIZE));
    }
  }, [hasPreviousPage, load, offset]);

  const submitCreate = useCallback(
    async (event: React.FormEvent): Promise<CreateChannelResponse | null> => {
      event.preventDefault();
      setCreateError(null);

      const trimmed = name.trim();
      if (!CHANNEL_NAME_PATTERN.test(trimmed)) {
        setNameError('Use 1-80 letters, numbers, spaces, hyphens, or underscores.');
        return null;
      }
      setNameError(null);

      setIsCreating(true);
      try {
        const created = await createChannel({ name: trimmed, is_private: isPrivate });
        setName('');
        setIsPrivate(false);
        return created;
      } catch (err) {
        setCreateError(err);
        return null;
      } finally {
        setIsCreating(false);
      }
    },
    [isPrivate, name],
  );

  const join = useCallback(async (channelId: string): Promise<boolean> => {
    setJoinError(null);
    setJoiningId(channelId);
    try {
      await joinChannel(channelId);
      // The joined channel is no longer "not yet a member" — drop it from
      // this browse list rather than waiting on a full re-fetch.
      setChannels((prev) => prev.filter((channel) => channel.id !== channelId));
      setTotal((prev) => Math.max(0, prev - 1));
      return true;
    } catch (err) {
      setJoinError(err);
      return false;
    } finally {
      setJoiningId(null);
    }
  }, []);

  return {
    name,
    setName,
    isPrivate,
    setIsPrivate,
    nameError,
    createError,
    isCreating,
    submitCreate,
    channels,
    total,
    offset,
    pageSize: PUBLIC_CHANNELS_PAGE_SIZE,
    isLoading,
    listError,
    hasNextPage,
    hasPreviousPage,
    nextPage,
    previousPage,
    joiningId,
    joinError,
    join,
  };
}
