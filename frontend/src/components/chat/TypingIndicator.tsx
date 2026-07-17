import type { JSX } from 'react';
import type { ChannelMemberSummary } from '../../api/types';

export interface TypingIndicatorProps {
  /** Currently-typing user ids (already 5s-auto-expired by the caller, F56). */
  userIds: string[];
  /** Identity lookup for display names — same source `MessageList` already
   * loads for message-author badges (`useChannelMembers`). A typing user
   * not yet present here (e.g. joined the channel after this client loaded
   * the member list) still renders, as "Someone", rather than being
   * silently dropped. */
  members: ReadonlyMap<string, ChannelMemberSummary>;
}

function displayName(userId: string, members: ReadonlyMap<string, ChannelMemberSummary>): string {
  const member = members.get(userId);
  if (member === undefined) {
    return 'Someone';
  }
  const fullName = `${member.first_name} ${member.last_name}`.trim();
  return fullName.length > 0 ? fullName : `@${member.username}`;
}

/** Renders "X is typing…" / "X and Y are typing…" / "N people are typing…"
 * for the joined conversation (F56). An `aria-live` region so screen-reader
 * users are notified of the transient state without it stealing focus
 * (`role="status"`, polite — matches the existing `AlertBanner`
 * info/success convention). Renders nothing when nobody is typing, so it
 * never leaves stale chrome in the layout. */
export function TypingIndicator({ userIds, members }: TypingIndicatorProps): JSX.Element | null {
  if (userIds.length === 0) {
    return null;
  }

  const names = userIds.map((id) => displayName(id, members));
  let text: string;
  if (names.length === 1) {
    text = `${names[0]} is typing…`;
  } else if (names.length === 2) {
    text = `${names[0]} and ${names[1]} are typing…`;
  } else {
    text = `${names.length} people are typing…`;
  }

  return (
    <p role="status" aria-live="polite" className="text-caption italic text-[var(--color-text-tertiary)]">
      {text}
    </p>
  );
}
