import type { JSX } from 'react';
import type { WsStatus } from '../../ws/socketClient';
import { AlertBanner } from '../ui/AlertBanner';

export interface ReconnectingBannerProps {
  status: WsStatus;
}

/** Shown only while a previously-open live connection is down and a
 * reconnect (backoff, or 4402 refresh-then-reconnect) is in flight — Flow K
 * step 1 (F55). Renders nothing once the socket is `open`, so it never
 * lingers over a healthy connection; also renders nothing during the very
 * first `connecting` attempt (that's an initial-load state, not a
 * reconnect). */
export function ReconnectingBanner({ status }: ReconnectingBannerProps): JSX.Element | null {
  if (status !== 'reconnecting') {
    return null;
  }

  return (
    <AlertBanner variant="warning" role="status">
      Reconnecting… live updates may be delayed until the connection is restored.
    </AlertBanner>
  );
}
