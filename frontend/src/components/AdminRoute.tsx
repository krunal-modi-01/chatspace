import type { JSX } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/** Guards a subtree of routes behind the System Admin role, in addition to
 * authentication. Mirrors `ProtectedRoute`; nest it under `ProtectedRoute`
 * (as in `App.tsx`) so bootstrapping/authentication are already resolved by
 * the time this renders. Non-admins are redirected to "/" and never see the
 * admin nav entry or screen. */
export function AdminRoute(): JSX.Element {
  const { user } = useAuth();

  if (user?.role !== 'system_admin') {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
