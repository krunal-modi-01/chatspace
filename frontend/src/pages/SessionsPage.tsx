import type { JSX } from 'react';
import { ErrorBanner } from '../components/ErrorBanner';
import { useSessions } from '../hooks/useSessions';

const FALLBACK_DEVICE_LABEL = 'Unknown device';

/** Lists the caller's active sessions/devices and allows revoking any
 * session other than the current one (logout is used for that). */
export function SessionsPage(): JSX.Element {
  const { sessions, isLoading, error, revokingId, revoke } = useSessions();

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-xl font-semibold text-gray-900">Active sessions</h1>

      {error !== null && <ErrorBanner error={error} />}

      {isLoading ? (
        <div role="status" aria-live="polite" className="text-sm text-gray-500">
          Loading sessions…
        </div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-gray-600">No active sessions found.</p>
      ) : (
        <ul className="divide-y divide-gray-200 rounded-md border border-gray-200">
          {sessions.map((session) => (
            <li
              key={session.session_id}
              className="flex items-center justify-between gap-4 px-4 py-3"
            >
              <div>
                <p className="text-sm font-medium text-gray-900">
                  {session.device_label ?? FALLBACK_DEVICE_LABEL}
                  {session.current && (
                    <span className="ml-2 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700">
                      This device
                    </span>
                  )}
                </p>
                <p className="text-xs text-gray-500">
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
                  className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
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
