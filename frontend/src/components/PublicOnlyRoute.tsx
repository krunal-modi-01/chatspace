import type { JSX } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/** Guards routes that should only be reachable while logged out (login,
 * register, password reset). Already-authenticated users are bounced to
 * the app shell instead of seeing the auth forms again. */
export function PublicOnlyRoute(): JSX.Element {
  const { isAuthenticated, isBootstrapping } = useAuth();

  if (isBootstrapping) {
    return (
      <div role="status" aria-live="polite" className="flex min-h-screen items-center justify-center">
        <span className="text-sm text-[var(--color-text-secondary)]">Loading…</span>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
