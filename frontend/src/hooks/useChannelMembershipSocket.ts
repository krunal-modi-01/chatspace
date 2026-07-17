import { useEffect } from 'react';
import { refreshAccessToken } from '../api/httpClient';
import type { MyChannelSummary } from '../api/types';
import { env } from '../config/env';
import { authStoreApi, useAuthStore } from '../store/authStore';
import { useMyChannelsStore } from '../store/myChannelsStore';
import type {
  ChannelMemberAddedFrame,
  ChannelMemberAddedPayload,
  ChannelMemberRemovedFrame,
  ChannelMemberRemovedPayload,
  ServerFrame,
} from '../ws/frames';
import { ReconnectingSocket } from '../ws/socketClient';

function buildWsUrl(): string {
  // Same no-token-in-URL rationale as `useConversationSocket` — the access
  // token travels via the `Sec-WebSocket-Protocol: bearer, <jwt>`
  // sub-protocol instead.
  return env.wsBaseUrl;
}

function isMemberAddedPayload(data: unknown): data is ChannelMemberAddedPayload {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const candidate = data as Partial<ChannelMemberAddedPayload>;
  const channel = candidate.channel;
  return (
    typeof candidate.user_id === 'string' &&
    typeof candidate.role === 'string' &&
    typeof candidate.joined_at === 'string' &&
    typeof channel === 'object' &&
    channel !== null &&
    typeof channel.id === 'string' &&
    typeof channel.name === 'string' &&
    typeof channel.is_private === 'boolean' &&
    typeof channel.created_by === 'string' &&
    typeof channel.created_at === 'string' &&
    typeof channel.member_count === 'number'
  );
}

function isMemberRemovedPayload(data: unknown): data is ChannelMemberRemovedPayload {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const candidate = data as Partial<ChannelMemberRemovedPayload>;
  return typeof candidate.channel_id === 'string' && typeof candidate.user_id === 'string';
}

/**
 * App-level (global) counterpart to `useConversationSocket` (T33/T51).
 * `useConversationSocket` only exists while a single conversation is open,
 * so it can never learn about a membership change for a channel the caller
 * isn't currently viewing — exactly the gap ADR-0012 closes with a
 * per-user `user:{user_id}` topic, auto-subscribed server-side at connect
 * (no `join` frame needed, unlike conversation topics).
 *
 * Mounted once, for the whole authenticated session (`AppShell`), this hook
 * owns a second, independent `/v1/ws` connection whose only job is to keep
 * the shared My Channels store (T50) in sync:
 * - `channel.member_added` → idempotent upsert by channel id (F74).
 * - `channel.member_removed` → idempotent remove by channel id (F75); if
 *   that channel is the one currently open, the store also raises the
 *   removal notice consumed by `useChannelRemovalNotice`.
 * - Every `open` transition (initial connect **and** every reconnect)
 *   re-runs the REST `GET /v1/channels` fetch — membership events are
 *   at-least-once with **no replay** (contract line 725, Flow L), so a
 *   client disconnected when a change occurred must catch up via a fresh
 *   list fetch, mirroring `useConversationSocket`'s message catch-up.
 * - Any other frame type (`message.*`, `typing`, `presence`, `error`,
 *   `pong`, or an unrecognized future value) is intentionally a no-op here
 *   (open enum — out of scope for this listener).
 */
export function useChannelMembershipSocket(): void {
  const hasSession = useAuthStore((state) => state.accessToken !== null);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    if (!hasSession) {
      return;
    }

    let cancelled = false;

    function applyFrame(frame: ServerFrame): void {
      if (frame.type === 'channel.member_added') {
        const data = (frame as ChannelMemberAddedFrame).data;
        if (!isMemberAddedPayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        const summary: MyChannelSummary = {
          id: data.channel.id,
          name: data.channel.name,
          is_private: data.channel.is_private,
          created_by: data.channel.created_by,
          created_at: data.channel.created_at,
          member_count: data.channel.member_count,
          my_role: data.role,
        };
        useMyChannelsStore.getState().upsertChannel(summary);
        return;
      }
      if (frame.type === 'channel.member_removed') {
        const data = (frame as ChannelMemberRemovedFrame).data;
        if (!isMemberRemovedPayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        useMyChannelsStore.getState().removeChannel(data.channel_id);
        return;
      }
      // `message.created/edited/deleted`, `typing`, `presence`, `error`,
      // `pong`, and any unrecognized `type` are intentionally no-ops here
      // (open enum, out of this listener's scope).
    }

    const socket = new ReconnectingSocket({
      buildUrl: buildWsUrl,
      getAccessToken: () => authStoreApi.getState().accessToken,
      refreshAccessToken,
      onStatusChange: (status) => {
        if (cancelled) {
          return;
        }
        if (status === 'open') {
          void useMyChannelsStore.getState().load();
        }
      },
      onFrame: (frame) => {
        if (!cancelled) {
          applyFrame(frame);
        }
      },
      onFatal: (reason) => {
        if (cancelled) {
          return;
        }
        if (reason === 'revoked' || reason === 'deactivated') {
          // Session is genuinely gone server-side — clear it locally too so
          // route guards redirect to /login, same handling as
          // `useConversationSocket`.
          clearSession();
        }
      },
    });

    socket.connect();

    return () => {
      cancelled = true;
      socket.destroy();
    };
  }, [hasSession, clearSession]);
}
