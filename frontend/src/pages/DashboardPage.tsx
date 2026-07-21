import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';

/** Protected landing page. DMs UI lands in a later task; channels/membership
 * shipped in T31 (messages themselves are T32). */
export function DashboardPage(): JSX.Element {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">
        Welcome{user ? `, ${user.first_name}` : ''}
      </h1>
      <Card className="flex flex-col items-start gap-3 text-left">
        <p className="text-subheading text-[var(--color-text-primary)]">Get started</p>
        <p className="text-body text-[var(--color-text-secondary)]">
          Create a channel or browse public channels to join. Your DMs will appear here once they’re available.
        </p>
        <Button as={Link} to="/channels">
          Browse channels
        </Button>
      </Card>
    </div>
  );
}
