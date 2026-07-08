import { useCallback, useEffect, useState } from 'react';
import { issueInvite, listInvites, resendInvite, revokeInvite } from '../api/adminApi';
import type { InviteListItem, InviteStatus } from '../api/types';

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Empty string means "all statuses" — the backend omits the filter
 * entirely rather than accepting an "all" sentinel value. */
export type InviteStatusFilter = InviteStatus | '';

/**
 * Drives the Invite Management screen: the issue-invite form (with inline
 * email-format validation) and the filterable invite list with
 * resend/revoke row actions. Kept out of the page component's JSX per the
 * "no inline business logic in JSX" convention.
 */
export function useInvites() {
  const [statusFilter, setStatusFilter] = useState<InviteStatusFilter>('');
  const [invites, setInvites] = useState<InviteListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [listError, setListError] = useState<unknown>(null);

  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [issueError, setIssueError] = useState<unknown>(null);
  const [isIssuing, setIsIssuing] = useState(false);

  const [actionId, setActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setListError(null);
    try {
      const response = await listInvites(statusFilter ? { status: statusFilter } : {});
      setInvites(response.items);
    } catch (err) {
      setListError(err);
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const submitInvite = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setIssueError(null);

      const trimmed = email.trim();
      if (!EMAIL_PATTERN.test(trimmed)) {
        setEmailError('Enter a valid email address.');
        return;
      }
      setEmailError(null);

      setIsIssuing(true);
      try {
        await issueInvite({ email: trimmed });
        setEmail('');
        await load();
      } catch (err) {
        setIssueError(err);
      } finally {
        setIsIssuing(false);
      }
    },
    [email, load],
  );

  const resend = useCallback(
    async (id: string) => {
      setActionError(null);
      setActionId(id);
      try {
        await resendInvite(id);
        await load();
      } catch (err) {
        setActionError(err);
      } finally {
        setActionId(null);
      }
    },
    [load],
  );

  const revoke = useCallback(async (id: string): Promise<boolean> => {
    setActionError(null);
    setActionId(id);
    try {
      await revokeInvite(id);
      setInvites((prev) => prev.filter((invite) => invite.id !== id));
      return true;
    } catch (err) {
      setActionError(err);
      return false;
    } finally {
      setActionId(null);
    }
  }, []);

  return {
    statusFilter,
    setStatusFilter,
    invites,
    isLoading,
    listError,
    email,
    setEmail,
    emailError,
    issueError,
    isIssuing,
    submitInvite,
    actionId,
    actionError,
    resend,
    revoke,
  };
}
