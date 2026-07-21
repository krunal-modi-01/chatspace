import type { JSX } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/** Guards a subtree of routes behind authentication. Unauthenticated
 * visitors are redirected to /login, preserving the intended destination
 * so they can be sent back after login. */
export function ProtectedRoute(): JSX.Element {
  const { isAuthenticated, isBootstrapping } = useAuth();
  const location = useLocation();

  if (isBootstrapping) {
    return (
      <div role="status" aria-live="polite" className="flex min-h-screen items-center justify-center">
        <span className="text-sm text-[var(--color-text-secondary)]">Loading…</span>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
