import type { JSX } from 'react';
import { useParams } from 'react-router-dom';
import { MessageList } from '../components/chat/MessageList';
import { AlertBanner } from '../components/ui/AlertBanner';

/**
 * Channel messaging surface (T32): REST-backed history/infinite-scroll,
 * optimistic send, author edit/delete, and identity badges. Channel
 * discovery/navigation (create/browse/join a channel, a channel list in the
 * app shell) is T31's scope — this page renders whatever `channelId` the
 * route was given; membership is enforced server-side (403/404) regardless.
 */
export function ChannelPage(): JSX.Element {
  const { channelId } = useParams<{ channelId: string }>();

  if (!channelId) {
    return (
      <AlertBanner variant="error" role="alert" title="Channel not found">
        No channel id was provided.
      </AlertBanner>
    );
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4">
      <h1 className="text-heading text-[var(--color-text-primary)]">Channel</h1>
      <MessageList channelId={channelId} />
    </div>
  );
}
