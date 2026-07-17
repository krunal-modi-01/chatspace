import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelPage } from './ChannelPage';
import * as channelsApi from '../../api/channelsApi';
import { useAuthStore } from '../../store/authStore';

vi.mock('../../api/channelsApi');

const { usePresenceAndTypingMock } = vi.hoisted(() => ({ usePresenceAndTypingMock: vi.fn() }));
vi.mock('../../hooks/usePresenceAndTyping', () => ({
  usePresenceAndTyping: (conversation: unknown) => usePresenceAndTypingMock(conversation),
}));

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

function renderAt(path = '/channels/chan-1') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/channels/:channelId" element={<ChannelPage />} />
        <Route path="/channels" element={<div>Channels list page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChannelPage — presence + typing wiring (T34)', () => {
  afterEach(() => {
    // See the matching comment in `ChannelPage.test.tsx`: unmount explicitly
    // before `resetAllMocks()` clears `usePresenceAndTypingMock`'s return
    // value, so a still-in-flight async update can't crash the component's
    // destructure while it's still mounted.
    cleanup();
    vi.resetAllMocks();
    useAuthStore.setState({ user: null });
  });

  beforeEach(() => {
    usePresenceAndTypingMock.mockReturnValue({
      status: 'closed',
      typingUserIds: [],
      presenceByUserId: new Map(),
      sendTyping: vi.fn(),
      fatalError: null,
    });
  });

  it('does not join a live conversation for a non-member (unauthorized topic)', async () => {
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-9',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 3,
      my_role: null,
    });

    renderAt();

    expect(await screen.findByRole('heading', { name: 'engineering' })).toBeInTheDocument();
    expect(usePresenceAndTypingMock).toHaveBeenLastCalledWith(null);
  });

  it('joins the channel conversation once membership is confirmed', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
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

    renderAt();

    await screen.findByText('@bob');
    expect(usePresenceAndTypingMock).toHaveBeenLastCalledWith({ kind: 'channel', channel_id: 'chan-1' });
  });

  it('renders an online indicator for a member with a live presence event', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
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
    usePresenceAndTypingMock.mockReturnValue({
      status: 'open',
      typingUserIds: [],
      presenceByUserId: new Map([['user-2', { state: 'online', lastSeen: null }]]),
      sendTyping: vi.fn(),
      fatalError: null,
    });

    renderAt();

    await screen.findByText('@bob');
    expect(screen.getByText('Online')).toBeInTheDocument();
  });

  it('renders a last-seen indicator for an offline member instead of a bare "Offline"', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
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
    usePresenceAndTypingMock.mockReturnValue({
      status: 'open',
      typingUserIds: [],
      presenceByUserId: new Map([['user-2', { state: 'offline', lastSeen: '2026-07-08T00:00:00.000Z' }]]),
      sendTyping: vi.fn(),
      fatalError: null,
    });

    renderAt();

    await screen.findByText('@bob');
    expect(screen.getByText(/last seen/i)).toBeInTheDocument();
  });

  it('shows nothing for a member with no observed presence event yet', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
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

    renderAt();

    await screen.findByText('@bob');
    expect(screen.queryByText('Online')).not.toBeInTheDocument();
    expect(screen.queryByText(/last seen/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Offline')).not.toBeInTheDocument();
  });

  it('renders the typing indicator for the joined conversation', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
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
    // `MessageList`'s own identity source (`useChannelMembers`) calls this
    // alias, not `listChannelMembers` directly — needed here so the typing
    // indicator can resolve `user-2` to a display name.
    vi.mocked(channelsApi.fetchChannelMembers).mockResolvedValue({
      items: [ADMIN_MEMBER, OTHER_MEMBER],
      total: 2,
    });
    usePresenceAndTypingMock.mockReturnValue({
      status: 'open',
      typingUserIds: ['user-2'],
      presenceByUserId: new Map(),
      sendTyping: vi.fn(),
      fatalError: null,
    });

    renderAt();

    expect(await screen.findByText('Bob Smith is typing…')).toBeInTheDocument();
  });
});
