import type { JSX } from 'react';
import { Outlet } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useLogout } from '../hooks/useLogout';

/** Top-level authenticated shell: header with current user + logout, and
 * a content outlet for feature screens added in T30+. */
export function AppShell(): JSX.Element {
  const { user } = useAuth();
  const { logoutAndRedirect, isLoggingOut } = useLogout();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
        <span className="text-lg font-semibold text-gray-900">chatspace</span>
        <div className="flex items-center gap-3">
          {user && <span className="text-sm text-gray-600">{user.username}</span>}
          <button
            type="button"
            onClick={logoutAndRedirect}
            disabled={isLoggingOut}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </header>
      <main className="flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
