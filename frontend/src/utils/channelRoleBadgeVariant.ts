import type { BadgeVariant } from '../components/ui/Badge';
import type { ChannelRole } from '../api/types';

/** Per-channel role → `Badge` variant (docs/design/DESIGN_SYSTEM.md §3.2:
 * `admin` → `accent`, `member` → `neutral`). `role` is an open enum
 * server-side (api-contract.md Conventions), so anything else falls back to
 * `neutral` rather than assuming a closed set.
 *
 * Shared between `MyChannelsNav` and `ChannelPage` (T58) — both rendered
 * this mapping identically; extracted here so there's one place to update
 * if it ever changes. */
export function channelRoleBadgeVariant(role: ChannelRole): BadgeVariant {
  return role === 'admin' ? 'accent' : 'neutral';
}
