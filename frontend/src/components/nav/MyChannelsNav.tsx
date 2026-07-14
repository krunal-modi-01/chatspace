import type { JSX } from 'react';
import { NavLink } from 'react-router-dom';
import { ErrorBanner } from '../ErrorBanner';
import { useMyChannels } from '../../hooks/useMyChannels';
import type { ChannelRole, MyChannelSummary } from '../../api/types';

const ROW_BASE_CLASSES =
  'flex flex-col gap-1 rounded-md px-2 py-2 text-body transition-colors duration-150 ease-out ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]';

function VisibilityBadge({ isPrivate }: { isPrivate: boolean }): JSX.Element {
  return (
    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-caption font-semibold dark:bg-gray-800/60">
      {isPrivate ? 'Private' : 'Public'}
    </span>
  );
}

function RoleBadge({ role }: { role: ChannelRole }): JSX.Element {
  const isAdmin = role === 'admin';
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-caption font-semibold capitalize ${
        isAdmin
          ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent)]'
          : 'bg-gray-100 text-gray-700 dark:bg-gray-800/60 dark:text-gray-300'
      }`}
    >
      {role}
    </span>
  );
}

function ChannelRow({ channel }: { channel: MyChannelSummary }): JSX.Element {
  return (
    <li>
      <NavLink
        to={`/channels/${channel.id}`}
        className={({ isActive }) =>
          `${ROW_BASE_CLASSES} ${
            isActive
              ? 'bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
              : 'text-[var(--color-text-primary)] hover:bg-[var(--color-surface-overlay)]'
          }`
        }
      >
        <span className="truncate font-medium">{channel.name}</span>
        <span className="flex items-center gap-1.5">
          <VisibilityBadge isPrivate={channel.is_private} />
          <RoleBadge role={channel.my_role} />
        </span>
      </NavLink>
    </li>
  );
}

/**
 * "My Channels" navigation list (T50, F73) — the primary logged-in
 * navigation surface. The app shell has no pre-existing sidebar (top-bar
 * nav only), so this component renders as a persistent sidebar panel
 * mounted once in `AppShell`, visible from every authenticated screen —
 * matching the PRD's framing of this list as the primary way a user finds
 * their conversations (including a private channel they were just added
 * to). Rows link into the existing `/channels/:channelId` view.
 *
 * Handles loading/empty/error states per PRD §11; live updates on
 * membership change (F74/F75) are T51, and the a11y finishing sweep is T52.
 */
export function MyChannelsNav(): JSX.Element {
  const { channels, isLoading, error } = useMyChannels();

  return (
    <nav aria-label="My channels" className="flex flex-col gap-3">
      <h2 className="px-2 text-subheading text-[var(--color-text-primary)]">Channels</h2>

      {error !== null && <ErrorBanner error={error} />}

      {isLoading ? (
        <div role="status" aria-live="polite" className="px-2 text-body text-[var(--color-text-secondary)]">
          Loading your channels…
        </div>
      ) : error === null && channels.length === 0 ? (
        <div className="px-2 text-body text-[var(--color-text-secondary)]">
          <p>You haven&apos;t joined any channels yet.</p>
          <NavLink
            to="/channels"
            className="mt-2 inline-block text-body font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
          >
            Browse public channels
          </NavLink>
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {channels.map((channel) => (
            <ChannelRow key={channel.id} channel={channel} />
          ))}
        </ul>
      )}
    </nav>
  );
}
