import { useCallback, useEffect, useState } from 'react';
import { deactivateUser, listAdminUsers, reactivateUser } from '../api/adminApi';
import type { AdminUser } from '../api/types';

/**
 * Drives the User Management screen: a searchable user list plus
 * deactivate/reactivate row actions. Deactivated users stay in the list
 * (never filtered out client-side). Kept out of the page component's JSX
 * per the "no inline business logic in JSX" convention.
 */
export function useAdminUsers() {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [listError, setListError] = useState<unknown>(null);

  const [actionId, setActionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setListError(null);
    try {
      const response = await listAdminUsers(query.trim() ? { q: query.trim() } : {});
      setUsers(response.items);
    } catch (err) {
      setListError(err);
    } finally {
      setIsLoading(false);
    }
  }, [query]);

  useEffect(() => {
    load();
  }, [load]);

  const search = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      load();
    },
    [load],
  );

  const deactivate = useCallback(async (id: string) => {
    setActionError(null);
    setActionId(id);
    try {
      const result = await deactivateUser(id);
      setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, is_active: result.is_active } : u)));
    } catch (err) {
      setActionError(err);
    } finally {
      setActionId(null);
    }
  }, []);

  const reactivate = useCallback(async (id: string) => {
    setActionError(null);
    setActionId(id);
    try {
      const result = await reactivateUser(id);
      setUsers((prev) => prev.map((u) => (u.id === id ? { ...u, is_active: result.is_active } : u)));
    } catch (err) {
      setActionError(err);
    } finally {
      setActionId(null);
    }
  }, []);

  return {
    query,
    setQuery,
    users,
    isLoading,
    listError,
    search,
    actionId,
    actionError,
    deactivate,
    reactivate,
  };
}
