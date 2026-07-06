import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { logout as logoutRequest } from '../api/authApi';
import { useAuthStore } from '../store/authStore';

/** Encapsulates the logout flow (server call best-effort + local session
 * clear + redirect) so no page component embeds this business logic
 * directly in JSX. */
export function useLogout() {
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const clearSession = useAuthStore((state) => state.clearSession);
  const navigate = useNavigate();

  const logoutAndRedirect = useCallback(async () => {
    setIsLoggingOut(true);
    try {
      await logoutRequest();
    } catch {
      // Logout is idempotent server-side; even if the call fails (e.g.
      // token already invalid) we still clear local session state below.
    } finally {
      clearSession();
      setIsLoggingOut(false);
      navigate('/login', { replace: true });
    }
  }, [clearSession, navigate]);

  return { logoutAndRedirect, isLoggingOut };
}
