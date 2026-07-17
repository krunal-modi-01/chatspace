import type { JSX } from 'react';
import { formatLastSeen, type PresenceState } from '../../ws/presenceStore';

export interface PresenceIndicatorProps {
  /** `undefined` means "no `presence` event has been observed for this user
   * yet" — deliberately distinct from `offline` (see `ws/presenceStore.ts`);
   * rendering nothing here (rather than a confident "Offline") avoids lying
   * about a peer's status this client simply hasn't heard about. */
  presence: PresenceState | undefined;
}

/** Renders a live online/offline dot + label for one user, driven by
 * `presence` WS events (F49 ref-counted online state, F50 durable
 * `last_seen` on the last disconnect). */
export function PresenceIndicator({ presence }: PresenceIndicatorProps): JSX.Element | null {
  if (presence === undefined) {
    return null;
  }

  const isOnline = presence.state === 'online';
  const label = isOnline ? 'Online' : formatLastSeen(presence.lastSeen);

  return (
    <span className="inline-flex items-center gap-1.5 text-caption text-[var(--color-text-tertiary)]">
      <span
        aria-hidden="true"
        className={`h-2 w-2 shrink-0 rounded-full ${
          isOnline ? 'bg-[var(--color-success)]' : 'bg-gray-400 dark:bg-gray-600'
        }`}
      />
      <span>{label}</span>
    </span>
  );
}
