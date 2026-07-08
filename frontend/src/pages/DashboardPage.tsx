import type { JSX } from 'react';
import { useAuth } from '../hooks/useAuth';
import { Card } from '../components/ui/Card';

/** Protected placeholder landing page. Channels/DMs UI lands in T31/T32. */
export function DashboardPage(): JSX.Element {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">
        Welcome{user ? `, ${user.first_name}` : ''}
      </h1>
      <Card className="flex flex-col items-start gap-1 text-left">
        <p className="text-subheading text-[var(--color-text-primary)]">No channels yet</p>
        <p className="text-body text-[var(--color-text-secondary)]">
          Your channels and DMs will appear here once they’re available.
        </p>
      </Card>
    </div>
  );
}
