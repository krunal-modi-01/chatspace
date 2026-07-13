import type { JSX } from 'react';
import type { Message } from '../../api/types';

export interface MessageTimelineProps {
  messages: Message[];
  /** Current user id, used only to distinguish "you" vs. others for this
   * minimal identity treatment — richer identity/avatar chrome is
   * T31/T32's message-list scope; this component is built to be dropped
   * into that view once it exists. */
  currentUserId?: string | null;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Renders a live conversation timeline: dedup'd, id-ordered messages
 * (F54) with `edited`/`deleted` state applied in place (F53). `role="log"`
 * + `aria-live="polite"` announces newly appended messages to assistive
 * tech without being disruptive (matches the "receive-oriented" nature of
 * the WS surface — nothing here is an interrupting alert). */
export function MessageTimeline({ messages, currentUserId }: MessageTimelineProps): JSX.Element {
  if (messages.length === 0) {
    return <p className="text-body text-[var(--color-text-secondary)]">No messages yet.</p>;
  }

  return (
    <ul aria-label="Conversation messages" role="log" aria-live="polite" className="flex flex-col gap-3">
      {messages.map((message) => {
        const isDeleted = message.deleted_at !== null;
        const isOwn = currentUserId != null && message.sender_id === currentUserId;

        return (
          <li
            key={message.id}
            className={`flex flex-col gap-0.5 rounded-md border border-[var(--color-border)] px-3 py-2 ${
              isOwn ? 'items-end' : 'items-start'
            }`}
          >
            <div className="flex items-center gap-2 text-caption text-[var(--color-text-tertiary)]">
              <span>{isOwn ? 'You' : message.sender_id}</span>
              <time dateTime={message.created_at}>{formatTimestamp(message.created_at)}</time>
              {message.edited_at !== null && !isDeleted && <span>(edited)</span>}
            </div>
            {isDeleted ? (
              <p className="text-body italic text-[var(--color-text-tertiary)]">This message was deleted.</p>
            ) : (
              <p className="text-body whitespace-pre-wrap text-[var(--color-text-primary)]">{message.content}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
