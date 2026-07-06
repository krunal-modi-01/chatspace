import { useAuthStore } from '../store/authStore';

/**
 * Read-only view of auth state for components. Mutations go through the
 * auth store's actions or the auth API + store combo directly (kept out of
 * this hook to avoid hiding business logic behind a hook that looks
 * read-only).
 */
export function useAuth() {
  const accessToken = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping);

  return {
    isAuthenticated: accessToken !== null,
    user,
    isBootstrapping,
  };
}
