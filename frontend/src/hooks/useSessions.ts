import { useCallback, useEffect, useState } from 'react';
import { listSessions, revokeSession } from '../api/authApi';
import type { SessionSummary } from '../api/types';

/**
 * Loads the caller's active sessions and exposes a revoke action for a
 * specific (non-current) session. Kept out of the page component's JSX per
 * the "no inline business logic in JSX" convention.
 */
export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await listSessions();
      setSessions(response.items);
    } catch (err) {
      setError(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const revoke = useCallback(async (sessionId: string) => {
    setRevokingId(sessionId);
    setError(null);
    try {
      await revokeSession(sessionId);
      setSessions((prev) => prev.filter((session) => session.session_id !== sessionId));
    } catch (err) {
      setError(err);
    } finally {
      setRevokingId(null);
    }
  }, []);

  return { sessions, isLoading, error, revokingId, revoke };
}
