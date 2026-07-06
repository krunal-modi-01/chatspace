import { useEffect } from 'react';
import { fetchCurrentUser } from '../api/authApi';
import { useAuthStore } from '../store/authStore';

/**
 * On app start, if a persisted access token exists, fetch the current user
 * to hydrate the store (and implicitly validate the token via the 401
 * refresh path baked into the HTTP client). Runs once per app mount.
 */
export function useSessionBootstrap(): void {
  const accessToken = useAuthStore((state) => state.accessToken);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);
  const setUser = useAuthStore((state) => state.setUser);
  const setBootstrapped = useAuthStore((state) => state.setBootstrapped);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    if (!isBootstrapping) {
      return;
    }
    if (!accessToken) {
      setBootstrapped();
      return;
    }

    let cancelled = false;
    fetchCurrentUser()
      .then((user) => {
        if (!cancelled) {
          setUser(user);
          setBootstrapped();
        }
      })
      .catch(() => {
        if (!cancelled) {
          clearSession();
        }
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isBootstrapping]);
}
