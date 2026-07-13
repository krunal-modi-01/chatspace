import { useCallback, useEffect, useState } from 'react';
import {
  addChannelMember,
  getChannel,
  joinChannel,
  leaveChannel,
  listChannelMembers,
  removeChannelMember,
  updateChannelMemberRole,
} from '../api/channelsApi';
import { ApiError } from '../api/problem';
import type { ChannelDetail, ChannelMember, ChannelRole } from '../api/types';

/** Offset page size for the member list — same 50 default/max the backend
 * enforces (`CHANNEL_MEMBERS_DEFAULT_LIMIT`/`_MAX_LIMIT`). */
const MEMBERS_PAGE_SIZE = 50;

function isFrozenConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/**
 * Best-effort, non-authoritative signal for the F37 zero-admin frozen
 * state: true once every member on record is visible (`items.length ===
 * total`) and none of them holds `admin`. This only fires when the full
 * member list fits on one page — the *authoritative* signal is always the
 * `409` a mutation attempt gets back (frozen contract: the leave/succession
 * endpoints never report the frozen state directly), which is handled
 * separately below regardless of whether this heuristic caught it first.
 */
function computeVisibleZeroAdmin(members: ChannelMember[], total: number): boolean {
  return members.length > 0 && members.length === total && members.every((member) => member.role !== 'admin');
}

/**
 * Drives the channel view screen: channel detail + member list, the
 * public-join affordance for a non-member viewing a public channel, leave
 * (with generic succession/zero-admin messaging — the API never reports
 * who was promoted or whether the channel is now frozen, so this hook does
 * not attempt to compute the heir), and admin-only membership mutations
 * (add/role-change/remove) with 409 zero-admin-frozen handling. Kept out of
 * the page component's JSX per the "no inline business logic in JSX"
 * convention.
 */
export function useChannelDetail(channelId: string) {
  const [channel, setChannel] = useState<ChannelDetail | null>(null);
  const [isLoadingChannel, setIsLoadingChannel] = useState(true);
  const [channelError, setChannelError] = useState<unknown>(null);

  const [members, setMembers] = useState<ChannelMember[]>([]);
  const [membersTotal, setMembersTotal] = useState(0);
  const [membersOffset, setMembersOffset] = useState(0);
  const [isLoadingMembers, setIsLoadingMembers] = useState(false);
  const [membersError, setMembersError] = useState<unknown>(null);

  const [isFrozen, setIsFrozen] = useState(false);

  const [isJoining, setIsJoining] = useState(false);
  const [joinError, setJoinError] = useState<unknown>(null);

  const [isLeaving, setIsLeaving] = useState(false);
  const [leaveError, setLeaveError] = useState<unknown>(null);

  const [actionUserId, setActionUserId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const [addUserId, setAddUserId] = useState('');
  const [addRole, setAddRole] = useState<ChannelRole>('member');
  const [isAdding, setIsAdding] = useState(false);
  const [addError, setAddError] = useState<unknown>(null);

  const loadMembers = useCallback(
    async (nextOffset: number): Promise<{ items: ChannelMember[]; total: number } | null> => {
      setIsLoadingMembers(true);
      setMembersError(null);
      try {
        const response = await listChannelMembers(channelId, {
          limit: MEMBERS_PAGE_SIZE,
          offset: nextOffset,
        });
        setMembers(response.items);
        setMembersTotal(response.total);
        setMembersOffset(nextOffset);
        if (computeVisibleZeroAdmin(response.items, response.total)) {
          setIsFrozen(true);
        }
        return response;
      } catch (err) {
        // A non-member viewing a (discoverable) public channel gets a 403
        // here — expected, not an error state; the join affordance covers it.
        if (!(err instanceof ApiError && err.status === 403)) {
          setMembersError(err);
        }
        return null;
      } finally {
        setIsLoadingMembers(false);
      }
    },
    [channelId],
  );

  const loadChannel = useCallback(async (): Promise<ChannelDetail | null> => {
    setIsLoadingChannel(true);
    setChannelError(null);
    try {
      const detail = await getChannel(channelId);
      setChannel(detail);
      return detail;
    } catch (err) {
      setChannelError(err);
      return null;
    } finally {
      setIsLoadingChannel(false);
    }
  }, [channelId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const detail = await loadChannel();
      if (!cancelled && detail && detail.my_role !== null) {
        await loadMembers(0);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadChannel, loadMembers]);

  const join = useCallback(async (): Promise<boolean> => {
    setJoinError(null);
    setIsJoining(true);
    try {
      await joinChannel(channelId);
      await loadChannel();
      await loadMembers(0);
      return true;
    } catch (err) {
      setJoinError(err);
      return false;
    } finally {
      setIsJoining(false);
    }
  }, [channelId, loadChannel, loadMembers]);

  const leave = useCallback(async (): Promise<boolean> => {
    setLeaveError(null);
    setIsLeaving(true);
    try {
      await leaveChannel(channelId);
      return true;
    } catch (err) {
      setLeaveError(err);
      return false;
    } finally {
      setIsLeaving(false);
    }
  }, [channelId]);

  const refreshAfterMutation = useCallback(async () => {
    await loadChannel();
    const response = await loadMembers(membersOffset);
    // A remove/role-change can shrink the total below the current (non-first)
    // page's offset — e.g. removing the last member on the last page. Reload
    // at the last valid page instead of stranding the view on an empty page.
    if (response && response.total > 0 && membersOffset >= response.total) {
      const lastValidOffset = Math.floor((response.total - 1) / MEMBERS_PAGE_SIZE) * MEMBERS_PAGE_SIZE;
      await loadMembers(lastValidOffset);
    }
  }, [loadChannel, loadMembers, membersOffset]);

  const changeRole = useCallback(
    async (userId: string, role: ChannelRole) => {
      setActionError(null);
      setActionUserId(userId);
      try {
        await updateChannelMemberRole(channelId, userId, { role });
        await refreshAfterMutation();
      } catch (err) {
        if (isFrozenConflict(err)) {
          setIsFrozen(true);
        }
        setActionError(err);
      } finally {
        setActionUserId(null);
      }
    },
    [channelId, refreshAfterMutation],
  );

  const removeMember = useCallback(
    async (userId: string) => {
      setActionError(null);
      setActionUserId(userId);
      try {
        await removeChannelMember(channelId, userId);
        await refreshAfterMutation();
      } catch (err) {
        if (isFrozenConflict(err)) {
          setIsFrozen(true);
        }
        setActionError(err);
      } finally {
        setActionUserId(null);
      }
    },
    [channelId, refreshAfterMutation],
  );

  const addMember = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setAddError(null);
      const trimmed = addUserId.trim();
      if (!trimmed) {
        return;
      }
      setIsAdding(true);
      try {
        await addChannelMember(channelId, { user_id: trimmed, role: addRole });
        setAddUserId('');
        setAddRole('member');
        await refreshAfterMutation();
      } catch (err) {
        if (isFrozenConflict(err)) {
          setIsFrozen(true);
        }
        setAddError(err);
      } finally {
        setIsAdding(false);
      }
    },
    [addRole, addUserId, channelId, refreshAfterMutation],
  );

  const hasNextMembersPage = membersOffset + MEMBERS_PAGE_SIZE < membersTotal;
  const hasPreviousMembersPage = membersOffset > 0;

  const nextMembersPage = useCallback(() => {
    if (hasNextMembersPage) {
      loadMembers(membersOffset + MEMBERS_PAGE_SIZE);
    }
  }, [hasNextMembersPage, loadMembers, membersOffset]);

  const previousMembersPage = useCallback(() => {
    if (hasPreviousMembersPage) {
      loadMembers(Math.max(0, membersOffset - MEMBERS_PAGE_SIZE));
    }
  }, [hasPreviousMembersPage, loadMembers, membersOffset]);

  // Best-effort "you are the only admin visible" flag — used only to decide
  // whether to show a generic (non-heir-computing) succession warning before
  // Leave; never presented as a guarantee since it depends on the full
  // member list being loaded.
  const isSoleVisibleAdmin =
    channel?.my_role === 'admin' &&
    members.length === membersTotal &&
    members.filter((member) => member.role === 'admin').length === 1;

  return {
    channel,
    isLoadingChannel,
    channelError,
    members,
    membersTotal,
    membersOffset,
    membersPageSize: MEMBERS_PAGE_SIZE,
    isLoadingMembers,
    membersError,
    isFrozen,
    isSoleVisibleAdmin,
    join,
    isJoining,
    joinError,
    leave,
    isLeaving,
    leaveError,
    actionUserId,
    actionError,
    changeRole,
    removeMember,
    addUserId,
    setAddUserId,
    addRole,
    setAddRole,
    isAdding,
    addError,
    addMember,
    hasNextMembersPage,
    hasPreviousMembersPage,
    nextMembersPage,
    previousMembersPage,
  };
}
