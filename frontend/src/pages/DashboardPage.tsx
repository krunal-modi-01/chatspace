import type { JSX } from 'react';
import { useAuth } from '../hooks/useAuth';

/** Protected placeholder landing page. Channels/DMs UI lands in T31/T32. */
export function DashboardPage(): JSX.Element {
  const { user } = useAuth();

  return (
    <div>
      <h1 className="text-xl font-semibold text-gray-900">
        Welcome{user ? `, ${user.first_name}` : ''}
      </h1>
      <p className="mt-2 text-sm text-gray-600">Your channels and DMs will appear here.</p>
    </div>
  );
}
