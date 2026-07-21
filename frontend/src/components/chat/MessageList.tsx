import { useEffect, useLayoutEffect, useMemo, useRef, type JSX } from 'react';
import type { ConversationTarget, Message } from '../../api/types';
import { useAuth } from '../../hooks/useAuth';
import { useChannelMembers } from '../../hooks/useChannelMembers';
import { useMessageHistory } from '../../hooks/useMessageHistory';
import { emptyMessageMap, sortedMessages, upsertMessages } from '../../ws/messageStore';
import type { WsStatus } from '../../ws/socketClient';
import { AlertBanner } from '../ui/AlertBanner';
import { Button } from '../ui/Button';
import { ErrorBanner } from '../ErrorBanner';
import { MessageComposer } from './MessageComposer';
import { MessageTimeline } from './MessageTimeline';
import { ReconnectingBanner } from './ReconnectingBanner';
import { TypingIndicator } from './TypingIndicator';

export interface MessageListProps {
  /** The channel to view/send in. DM support is out of this task's scope
   * (T32 is scoped to channel messaging per the task breakdown), though
   * `useMessageHistory`/`messagesApi` are written generically over
   * `ConversationTarget` for that future reuse. */
  channelId: string;
  /** Live presence/typing wiring (T34), owned by the caller
   * (`usePresenceAndTyping`) so the same connection also drives the
   * channel's member-list presence indicators — all optional so this
   * component keeps working standalone (existing call sites/tests) without
   * a live connection established. */
  typingUserIds?: string[];
  onTyping?: () => void;
  wsStatus?: WsStatus;
  /** Live `message.created`/`message.edited`/`message.deleted` events for
   * this channel (T33/T51 integration), owned by the caller
   * (`useConversationSocket`) so the same hook can also serve future
   * multi-surface reuse. Merged with REST history by id below — live wins
   * on a same-id conflict (it's the freshest source for another member's
   * edit/delete), so other members' messages render without waiting for a
   * refetch. Optional/defaults to empty so this component keeps working
   * standalone (existing call sites/tests) without a live connection
   * established. */
  liveMessages?: Message[];
}

function scrollToBottom(el: HTMLElement | null): void {
  if (el && typeof el.scrollTo === 'function') {
    el.scrollTo({ top: el.scrollHeight });
  }
}

/** Ties together REST history/infinite-scroll, optimistic send, author
 * edit/delete, and identity lookup into the full channel messaging surface
 * (T32). Live WS delivery (T33) is merged in via the optional
 * `liveMessages` prop (T51 integration) — see that prop's doc comment for
 * the merge precedence. */
export function MessageList({
  channelId,
  typingUserIds = [],
  onTyping,
  wsStatus = 'closed',
  liveMessages = [],
}: MessageListProps): JSX.Element {
  const { user } = useAuth();
  const currentUserId = user?.id ?? null;

  const target: ConversationTarget = { kind: 'channel', channel_id: channelId };
  const {
    messages: historyMessages,
    pendingSends,
    isLoadingInitial,
    isLoadingOlder,
    hasMoreOlder,
    historyError,
    actionError,
    sendMessage,
    retrySend,
    discardFailedSend,
    loadOlder,
    retryInitialLoad,
    editMessage,
    deleteMessage,
  } = useMessageHistory(target, currentUserId);

  // Merges REST-sourced history with live socket events by id, using the
  // same dedup/upsert helper both sources already build on
  // (`ws/messageStore`). Live wins on a same-id conflict — it's the
  // freshest source for another member's edit/delete arriving after the
  // page's initial history fetch.
  const messages = useMemo(() => {
    if (liveMessages.length === 0) {
      return historyMessages;
    }
    const merged = upsertMessages(upsertMessages(emptyMessageMap(), historyMessages), liveMessages);
    return sortedMessages(merged);
  }, [historyMessages, liveMessages]);

  const { membersById, error: membersError } = useChannelMembers(channelId);

  const scrollRef = useRef<HTMLDivElement>(null);
  const hasScrolledInitialRef = useRef(false);
  /** Captured immediately before a "load older" fetch so the layout effect
   * below can restore the user's visual scroll position once the older
   * batch is prepended — otherwise `scrollTop` stays fixed in pixels while
   * content grows above it and the view visibly jumps. */
  const pendingOlderScrollRef = useRef<{ scrollTop: number; scrollHeight: number } | null>(null);

  useEffect(() => {
    if (!isLoadingInitial && !hasScrolledInitialRef.current) {
      hasScrolledInitialRef.current = true;
      scrollToBottom(scrollRef.current);
    }
  }, [isLoadingInitial]);

  useEffect(() => {
    if (pendingSends.length > 0) {
      scrollToBottom(scrollRef.current);
    }
  }, [pendingSends.length]);

  // Runs synchronously after the DOM commits the prepended "older" messages
  // (before paint), so the restored scrollTop never has a chance to flash
  // the pre-adjustment (jumped) position.
  useLayoutEffect(() => {
    const pending = pendingOlderScrollRef.current;
    const el = scrollRef.current;
    if (pending === null || el === null) {
      return;
    }
    pendingOlderScrollRef.current = null;
    const heightDelta = el.scrollHeight - pending.scrollHeight;
    el.scrollTop = pending.scrollTop + heightDelta;
  }, [messages]);

  function handleLoadOlder(): void {
    const el = scrollRef.current;
    if (el) {
      pendingOlderScrollRef.current = { scrollTop: el.scrollTop, scrollHeight: el.scrollHeight };
    }
    void loadOlder();
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <ReconnectingBanner status={wsStatus} />

      {membersError !== null && (
        <AlertBanner variant="warning" role="status">
          Could not load member details — messages will show sender ids instead of names until this is retried.
        </AlertBanner>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto rounded-lg border border-[var(--color-border)] p-3">
        {isLoadingInitial ? (
          <p role="status" className="text-body text-[var(--color-text-secondary)]">
            Loading messages…
          </p>
        ) : historyError !== null ? (
          <div className="flex flex-col gap-3">
            <ErrorBanner error={historyError} />
            <Button type="button" variant="secondary" onClick={retryInitialLoad}>
              Retry
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {hasMoreOlder && (
              <Button
                type="button"
                variant="secondary"
                className="self-center"
                isLoading={isLoadingOlder}
                loadingText="Loading older messages…"
                onClick={handleLoadOlder}
              >
                Load older messages
              </Button>
            )}

            <MessageTimeline
              messages={messages}
              currentUserId={currentUserId}
              members={membersById}
              onEdit={editMessage}
              onDelete={deleteMessage}
            />

            {pendingSends.length > 0 && (
              <ul aria-label="Messages being sent" className="flex flex-col gap-2">
                {pendingSends.map((pending) => (
                  <li
                    key={pending.id}
                    className="flex flex-col items-end gap-1 rounded-md border border-dashed border-[var(--color-border)] px-3 py-2 opacity-80"
                  >
                    <p className="text-body whitespace-pre-wrap text-[var(--color-text-primary)]">{pending.content}</p>
                    {pending.status === 'sending' ? (
                      <span role="status" className="text-caption text-[var(--color-text-tertiary)]">
                        Sending…
                      </span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span role="alert" className="text-caption text-[var(--color-danger)]">
                          {pending.error ?? 'Failed to send.'}
                          {pending.retryAfterSeconds !== undefined && ` Try again in ${pending.retryAfterSeconds}s.`}
                        </span>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-[var(--color-accent)]! hover:text-[var(--color-accent-hover)]!"
                          onClick={() => void retrySend(pending.id)}
                        >
                          Retry
                        </Button>
                        <Button type="button" variant="ghost" size="sm" onClick={() => discardFailedSend(pending.id)}>
                          Discard
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {actionError !== null && <ErrorBanner error={actionError} />}

      <TypingIndicator userIds={typingUserIds} members={membersById} />

      <MessageComposer onSend={sendMessage} disabled={isLoadingInitial} onTyping={onTyping} />
    </div>
  );
}
