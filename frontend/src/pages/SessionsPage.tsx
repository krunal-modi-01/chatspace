import type { JSX } from 'react';
import { ErrorBanner } from '../components/ErrorBanner';
import { Badge } from '../components/ui/Badge';
import { Card } from '../components/ui/Card';
import { useSessions } from '../hooks/useSessions';

const FALLBACK_DEVICE_LABEL = 'Unknown device';

/** Lists the caller's active sessions/devices and allows revoking any
 * session other than the current one (logout is used for that). */
export function SessionsPage(): JSX.Element {
  const { sessions, isLoading, error, revokingId, revoke } = useSessions();

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">Active sessions</h1>

      {error !== null && <ErrorBanner error={error} />}

      {isLoading ? (
        <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
          Loading sessions…
        </div>
      ) : sessions.length === 0 ? (
        <Card className="text-body text-[var(--color-text-secondary)]">No active sessions found.</Card>
      ) : (
        <ul className="divide-y divide-[var(--color-border)] rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)]">
          {sessions.map((session) => (
            <li
              key={session.session_id}
              className="flex items-center justify-between gap-4 px-4 py-3"
            >
              <div>
                <p className="text-body font-medium text-[var(--color-text-primary)]">
                  {session.device_label ?? FALLBACK_DEVICE_LABEL}
                  {session.current && (
                    <Badge variant="accent" className="ml-2">
                      This device
                    </Badge>
                  )}
                </p>
                <p className="text-caption text-[var(--color-text-tertiary)]">
                  Signed in {new Date(session.created_at).toLocaleString()}
                  {session.last_seen_at &&
                    ` · Last active ${new Date(session.last_seen_at).toLocaleString()}`}
                </p>
              </div>
              {!session.current && (
                <button
                  type="button"
                  onClick={() => revoke(session.session_id)}
                  disabled={revokingId === session.session_id}
                  className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-body font-medium text-[var(--color-text-primary)] transition-colors duration-150 ease-out hover:bg-[var(--color-surface-raised)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {revokingId === session.session_id ? 'Revoking…' : 'Revoke'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
