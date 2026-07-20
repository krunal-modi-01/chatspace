import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../api/types';
import { useAuthStore } from '../../store/authStore';
import { useMyChannelsStore } from '../../store/myChannelsStore';

// Regression coverage for the live-message delivery gap: `ChannelPage` used
// to only ever wire up `usePresenceAndTyping` (typing/presence only, and it
// explicitly no-ops `message.*` frames — see that hook's docstring) while
// `MessageList`/`useMessageHistory` were REST-only. A `message.created` from
// another member never reached the rendered timeline without a full page
// refresh, even though `useConversationSocket` (T33) already handled exactly
// this frame — it was simply never called anywhere in the app. These tests
// exercise the real (unmocked) `useConversationSocket` hook, stubbing only
// the WS transport it sits on top of, so they fail on the pre-fix code
// (`ChannelPage` never constructed this socket at all) and pass once it's
// wired through to `MessageList`.

vi.mock('../../api/channelsApi');

const { fetchMessageHistoryMock } = vi.hoisted(() => ({ fetchMessageHistoryMock: vi.fn() }));
vi.mock('../../api/messagesApi', () => ({
  fetchMessageHistory: fetchMessageHistoryMock,
  sendMessage: vi.fn(),
  editMessage: vi.fn(),
  deleteMessage: vi.fn(),
}));

const { fetchMissedMessagesMock } = vi.hoisted(() => ({ fetchMissedMessagesMock: vi.fn() }));
vi.mock('../../ws/catchUp', () => ({
  fetchMissedMessages: fetchMissedMessagesMock,
}));

const { socketInstances } = vi.hoisted(() => ({
  socketInstances: [] as FakeReconnectingSocket[],
}));

class FakeReconnectingSocket {
  connect = vi.fn();
  join = vi.fn();
  leave = vi.fn();
  destroy = vi.fn();
  sendTyping = vi.fn();
  options: Record<string, unknown>;

  constructor(options: Record<string, unknown>) {
    this.options = options;
    socketInstances.push(this);
  }
}

vi.mock('../../ws/socketClient', () => ({
  ReconnectingSocket: FakeReconnectingSocket,
}));

// The presence/typing socket is a genuinely separate concern (not
// consolidated with `useConversationSocket` yet, by design — see
// `usePresenceAndTyping`'s docstring) and isn't under test here.
const { usePresenceAndTypingMock } = vi.hoisted(() => ({ usePresenceAndTypingMock: vi.fn() }));
vi.mock('../../hooks/usePresenceAndTyping', () => ({
  usePresenceAndTyping: () => usePresenceAndTypingMock(),
}));

const { ChannelPage } = await import('./ChannelPage');
const channelsApi = await import('../../api/channelsApi');

const CHANNEL_ID = 'chan-1';

const CURRENT_USER = {
  id: 'user-1',
  username: 'alice',
  email: 'alice@example.com',
  first_name: 'Alice',
  last_name: 'Doe',
  avatar_url: null,
  role: 'user' as const,
  is_active: true,
  last_seen: null,
  created_at: '2026-07-08T00:00:00.000Z',
};

const ADMIN_MEMBER = {
  user_id: 'user-1',
  username: 'alice',
  first_name: 'Alice',
  last_name: 'Doe',
  avatar_url: null,
  role: 'admin' as const,
  joined_at: '2026-07-01T00:00:00.000Z',
};

const OTHER_MEMBER = {
  user_id: 'user-2',
  username: 'bob',
  first_name: 'Bob',
  last_name: 'Smith',
  avatar_url: null,
  role: 'member' as const,
  joined_at: '2026-07-02T00:00:00.000Z',
};

// Opaque, non-secret placeholder fixtures — matching the convention used in
// `useConversationSocket.test.tsx` (no `token: "<value>"`-shaped literal).
const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

function msg(id: string, overrides: Partial<Message> = {}): Message {
  return {
    id,
    channel_id: CHANNEL_ID,
    recipient_id: null,
    sender_id: OTHER_MEMBER.user_id,
    content: `content-${id}`,
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function currentSocket(): FakeReconnectingSocket {
  const socket = socketInstances.at(-1);
  if (!socket) throw new Error('no socket constructed');
  return socket;
}

function renderAt(path = `/channels/${CHANNEL_ID}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/channels/:channelId" element={<ChannelPage />} />
        <Route path="/channels" element={<div>Channels list page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChannelPage — live message delivery (T51 regression)', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    fetchMessageHistoryMock.mockReset().mockResolvedValue({ items: [], next_cursor: null });
    fetchMissedMessagesMock.mockReset().mockResolvedValue({ messages: [], truncated: false });
    usePresenceAndTypingMock.mockReset().mockReturnValue({
      status: 'closed',
      typingUserIds: [],
      presenceByUserId: new Map(),
      sendTyping: vi.fn(),
      fatalError: null,
    });
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: CURRENT_USER,
      isBootstrapping: false,
    });

    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: CHANNEL_ID,
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 2,
      my_role: 'admin',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({
      items: [ADMIN_MEMBER, OTHER_MEMBER],
      total: 2,
    });
    vi.mocked(channelsApi.fetchChannelMembers).mockResolvedValue({
      items: [ADMIN_MEMBER, OTHER_MEMBER],
      total: 2,
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    useAuthStore.setState({ accessToken: null, refreshToken: null, user: null, isBootstrapping: false });
    useMyChannelsStore.setState({ viewedChannelId: null, removedChannelId: null });
  });

  it('renders a message.created event from a different sender live, with no refetch or remount', async () => {
    renderAt();

    await screen.findByText('@bob');
    await screen.findByText('No messages yet.');
    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(1);

    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'message.created',
        conversation: { kind: 'channel', channel_id: CHANNEL_ID },
        data: msg('01J8LIVE0000000000000000000', { sender_id: OTHER_MEMBER.user_id, content: 'hello from bob, live' }),
      });
    });

    expect(await screen.findByText('hello from bob, live')).toBeInTheDocument();
    // No REST refetch was triggered to surface the live message.
    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(1);
  });

  it('reflects a live message.edited event from another sender in the timeline', async () => {
    renderAt();
    await screen.findByText('@bob');

    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'message.created',
        conversation: { kind: 'channel', channel_id: CHANNEL_ID },
        data: msg('01J8LIVE0000000000000000000', { content: 'original' }),
      });
    });
    await screen.findByText('original');

    act(() => {
      onFrame({
        type: 'message.edited',
        conversation: { kind: 'channel', channel_id: CHANNEL_ID },
        data: msg('01J8LIVE0000000000000000000', {
          content: 'edited live',
          edited_at: '2026-07-02T15:00:00.000Z',
        }),
      });
    });

    expect(await screen.findByText('edited live')).toBeInTheDocument();
    expect(screen.queryByText('original')).not.toBeInTheDocument();
  });

  it('reflects a live message.deleted event from another sender in the timeline', async () => {
    renderAt();
    await screen.findByText('@bob');

    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'message.created',
        conversation: { kind: 'channel', channel_id: CHANNEL_ID },
        data: msg('01J8LIVE0000000000000000000', { content: 'to be deleted' }),
      });
    });
    await screen.findByText('to be deleted');

    act(() => {
      onFrame({
        type: 'message.deleted',
        conversation: { kind: 'channel', channel_id: CHANNEL_ID },
        data: {
          id: '01J8LIVE0000000000000000000',
          conversation: { kind: 'channel', channel_id: CHANNEL_ID },
          deleted_at: '2026-07-02T15:00:00.000Z',
        },
      });
    });

    expect(await screen.findByText('This message was deleted.')).toBeInTheDocument();
    expect(screen.queryByText('to be deleted')).not.toBeInTheDocument();
  });
});
