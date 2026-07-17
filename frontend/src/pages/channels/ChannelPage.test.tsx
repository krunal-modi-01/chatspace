import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChannelPage } from './ChannelPage';
import * as channelsApi from '../../api/channelsApi';
import { ApiError } from '../../api/problem';
import { useAuthStore } from '../../store/authStore';
import { useMyChannelsStore } from '../../store/myChannelsStore';

vi.mock('../../api/channelsApi');

// `usePresenceAndTyping` opens a real `/v1/ws` connection when unmocked —
// none of these tests exercise presence/typing (see `ChannelPage.presence.test.tsx`
// for that coverage), so it is stubbed out here the same way `useConversationSocket.test.tsx`
// stubs `ReconnectingSocket` directly. `vi.hoisted` is required (not a bare
// module-scope `const`) because `vi.mock` factories run before this file's
// own top-level statements, per vitest's hoisting semantics.
const { usePresenceAndTypingMock } = vi.hoisted(() => ({ usePresenceAndTypingMock: vi.fn() }));
vi.mock('../../hooks/usePresenceAndTyping', () => ({
  usePresenceAndTyping: () => usePresenceAndTypingMock(),
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

describe('ChannelPage', () => {
  afterEach(() => {
    // Explicit `cleanup()` *before* resetting mocks (rather than relying on
    // `@testing-library/react`'s own auto-registered `afterEach`, which — by
    // hook-nesting order — runs *after* this describe-scoped `afterEach`):
    // a still-in-flight async update from a test that didn't `await` every
    // effect to settle (e.g. a mutation's refetch) can otherwise fire a
    // re-render against an already-`resetAllMocks()`-cleared
    // `usePresenceAndTypingMock` (default `vi.fn()` return of `undefined`)
    // while the component is still mounted, crashing the destructure in
    // `ChannelPage.tsx`. Unmounting first removes that window entirely.
    cleanup();
    vi.resetAllMocks();
    useAuthStore.setState({ user: null });
    useMyChannelsStore.setState({ viewedChannelId: null, removedChannelId: null });
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

  it('shows a not-found error when the channel 404s (private/non-existent, uniform)', async () => {
    vi.mocked(channelsApi.getChannel).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/not-found',
        title: 'Not Found',
        status: 404,
        detail: 'No such channel.',
        instance: '/v1/channels/chan-1',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    renderAt();

    expect(await screen.findByText('No such channel.')).toBeInTheDocument();
  });

  it('offers a Join affordance for a non-member viewing a public channel', async () => {
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
    expect(screen.getByRole('button', { name: /join channel/i })).toBeInTheDocument();
    expect(screen.getByText(/not a member of this channel yet/i)).toBeInTheDocument();
    expect(channelsApi.listChannelMembers).not.toHaveBeenCalled();
  });

  it('renders the member list and admin controls for a channel admin', async () => {
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

    expect(await screen.findByText('@bob')).toBeInTheDocument();
    expect(screen.getByText('(you)')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /add a member/i })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /remove/i })).toHaveLength(2);
  });

  it('does not show admin controls for a plain member', async () => {
    useAuthStore.setState({ user: { ...CURRENT_USER, id: 'user-2' } });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 2,
      my_role: 'member',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({
      items: [ADMIN_MEMBER, OTHER_MEMBER],
      total: 2,
    });

    renderAt();

    await screen.findByText('@bob');
    expect(screen.queryByRole('heading', { name: /add a member/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
  });

  it('leaves the channel and navigates back to the channel list', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-9',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 2,
      my_role: 'member',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({
      items: [{ ...ADMIN_MEMBER, user_id: 'user-9' }, { ...OTHER_MEMBER, user_id: 'user-1', role: 'member' }],
      total: 2,
    });
    vi.mocked(channelsApi.leaveChannel).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderAt();

    await user.click(await screen.findByRole('button', { name: /leave channel/i }));
    await user.click(screen.getByRole('button', { name: /confirm leave/i }));

    await waitFor(() => {
      expect(channelsApi.leaveChannel).toHaveBeenCalledWith('chan-1');
    });
    expect(await screen.findByText('Channels list page')).toBeInTheDocument();
  });

  it('surfaces the zero-admin frozen 409 with the exact affordance copy on a role change', async () => {
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
    vi.mocked(channelsApi.updateChannelMemberRole).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'This channel currently has no admins; membership mutation is blocked.',
        instance: '/v1/channels/chan-1/members/user-2',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('@bob');
    const roleSelects = screen.getAllByRole('combobox');
    // Bob's row is the second data row's select (Alice's own row is first).
    await user.selectOptions(roleSelects[1], 'admin');

    expect(
      await screen.findByText('This channel currently has no admins — membership changes are blocked.'),
    ).toBeInTheDocument();
    expect(await screen.findByText('No admins')).toBeInTheDocument();
  });

  it('shows the zero-admin frozen banner proactively when the full member list has no admins (no mutation needed)', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 1,
      my_role: 'member',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({
      items: [{ ...OTHER_MEMBER, user_id: 'user-1', role: 'member' }],
      total: 1,
    });

    renderAt();

    expect(await screen.findByText('No admins')).toBeInTheDocument();
    expect(channelsApi.updateChannelMemberRole).not.toHaveBeenCalled();
    expect(channelsApi.removeChannelMember).not.toHaveBeenCalled();
  });

  it('requires a second explicit confirm before an admin can change their own role', async () => {
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
    vi.mocked(channelsApi.updateChannelMemberRole).mockResolvedValue({
      channel_id: 'chan-1',
      user_id: 'user-1',
      role: 'member',
      joined_at: '2026-07-01T00:00:00.000Z',
    });

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('@bob');
    const roleSelects = screen.getAllByRole('combobox');
    // Alice's own row is the first data row's select.
    await user.selectOptions(roleSelects[0], 'member');

    // The select change alone must not fire the mutation — it only stages it.
    expect(channelsApi.updateChannelMemberRole).not.toHaveBeenCalled();
    expect(await screen.findByText('Change your own role to member?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => {
      expect(channelsApi.updateChannelMemberRole).toHaveBeenCalledWith('chan-1', 'user-1', { role: 'member' });
    });
  });

  it('cancels a self-remove request without calling the API', async () => {
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

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('@bob');
    const removeButtons = screen.getAllByRole('button', { name: /^remove$/i });
    // Alice's own row is the first data row.
    await user.click(removeButtons[0]);

    expect(await screen.findByText('Remove yourself from this channel?')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^cancel$/i }));

    expect(screen.queryByText('Remove yourself from this channel?')).not.toBeInTheDocument();
    expect(channelsApi.removeChannelMember).not.toHaveBeenCalled();
  });

  it('adds a member and refreshes the member list', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 1,
      my_role: 'admin',
    });
    vi.mocked(channelsApi.listChannelMembers)
      .mockResolvedValueOnce({ items: [ADMIN_MEMBER], total: 1 })
      .mockResolvedValueOnce({ items: [ADMIN_MEMBER, OTHER_MEMBER], total: 2 });
    vi.mocked(channelsApi.addChannelMember).mockResolvedValue({
      channel_id: 'chan-1',
      user_id: 'user-2',
      role: 'member',
      joined_at: '2026-07-08T00:00:00.000Z',
    });

    const user = userEvent.setup();
    renderAt();

    await screen.findByRole('heading', { name: /add a member/i });
    await user.type(screen.getByLabelText(/user id/i), 'user-2');
    await user.click(screen.getByRole('button', { name: /^add member$/i }));

    await waitFor(() => {
      expect(channelsApi.addChannelMember).toHaveBeenCalledWith('chan-1', { user_id: 'user-2', role: 'member' });
    });
    expect(await screen.findByText('@bob')).toBeInTheDocument();
  });

  it('surfaces the zero-admin frozen 409 with the exact affordance copy on add-member', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 1,
      my_role: 'admin',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({ items: [ADMIN_MEMBER], total: 1 });
    vi.mocked(channelsApi.addChannelMember).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'This channel currently has no admins; membership mutation is blocked.',
        instance: '/v1/channels/chan-1/members',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderAt();

    await screen.findByRole('heading', { name: /add a member/i });
    await user.type(screen.getByLabelText(/user id/i), 'user-2');
    await user.click(screen.getByRole('button', { name: /^add member$/i }));

    expect(
      await screen.findByText('This channel currently has no admins — membership changes are blocked.'),
    ).toBeInTheDocument();
    expect(await screen.findByText('No admins')).toBeInTheDocument();
  });

  it('removes a non-self member and refreshes the member list', async () => {
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
    vi.mocked(channelsApi.listChannelMembers)
      .mockResolvedValueOnce({ items: [ADMIN_MEMBER, OTHER_MEMBER], total: 2 })
      .mockResolvedValueOnce({ items: [ADMIN_MEMBER], total: 1 });
    vi.mocked(channelsApi.removeChannelMember).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('@bob');
    const removeButtons = screen.getAllByRole('button', { name: /^remove$/i });
    // Bob's row is the second data row.
    await user.click(removeButtons[1]);

    await waitFor(() => {
      expect(channelsApi.removeChannelMember).toHaveBeenCalledWith('chan-1', 'user-2');
    });
    await waitFor(() => {
      expect(screen.queryByText('@bob')).not.toBeInTheDocument();
    });
  });

  it('surfaces the zero-admin frozen 409 with the exact affordance copy on remove-member', async () => {
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
    vi.mocked(channelsApi.removeChannelMember).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'This channel currently has no admins; membership mutation is blocked.',
        instance: '/v1/channels/chan-1/members/user-2',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('@bob');
    const removeButtons = screen.getAllByRole('button', { name: /^remove$/i });
    await user.click(removeButtons[1]);

    expect(
      await screen.findByText('This channel currently has no admins — membership changes are blocked.'),
    ).toBeInTheDocument();
    expect(await screen.findByText('No admins')).toBeInTheDocument();
  });

  it('clamps back to a valid page after a removal empties the current (non-first) page', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 51,
      my_role: 'admin',
    });

    let total = 51;
    vi.mocked(channelsApi.listChannelMembers).mockImplementation(async (_channelId, params = {}) => {
      const offset = (params as { offset?: number }).offset ?? 0;
      if (offset === 0) {
        return { items: [ADMIN_MEMBER], total };
      }
      return { items: total > 50 ? [OTHER_MEMBER] : [], total };
    });
    vi.mocked(channelsApi.removeChannelMember).mockImplementation(async () => {
      total = 50;
    });

    const user = userEvent.setup();
    renderAt();

    await screen.findByText(/of 51/);
    await user.click(screen.getByRole('button', { name: /^next$/i }));

    await screen.findByText('@bob');
    await user.click((await screen.findAllByRole('button', { name: /^remove$/i }))[0]);

    await waitFor(() => {
      expect(channelsApi.removeChannelMember).toHaveBeenCalledWith('chan-1', 'user-2');
    });

    // The offset-50 page is now empty (total shrank to 50) — the hook should
    // clamp back to the last valid page (offset 0) instead of stranding the
    // view on "No members found".
    await waitFor(() => {
      const lastCall = vi.mocked(channelsApi.listChannelMembers).mock.calls.at(-1);
      expect(lastCall?.[1]).toEqual({ limit: 50, offset: 0 });
    });
    expect(await screen.findByText('@alice')).toBeInTheDocument();
    expect(screen.queryByText('No members found.')).not.toBeInTheDocument();
  });

  it('exits gracefully with a specific message when a live event removes the currently open channel (F75, Flow L 4a)', async () => {
    useAuthStore.setState({ user: CURRENT_USER });
    vi.mocked(channelsApi.getChannel).mockResolvedValue({
      id: 'chan-1',
      name: 'engineering',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-01T00:00:00.000Z',
      member_count: 2,
      my_role: 'member',
    });
    vi.mocked(channelsApi.listChannelMembers).mockResolvedValue({
      items: [ADMIN_MEMBER, OTHER_MEMBER],
      total: 2,
    });

    const user = userEvent.setup();
    renderAt();

    expect(await screen.findByRole('heading', { name: 'engineering' })).toBeInTheDocument();
    // The removal notice can only ever apply while this exact channel is
    // registered as "currently viewed" — confirms the mount-time handoff to
    // the shared store this screen relies on (`useChannelRemovalNotice`).
    expect(useMyChannelsStore.getState().viewedChannelId).toBe('chan-1');

    // Simulates the app-level `useChannelMembershipSocket` applying a live
    // `channel.member_removed` event for the channel currently open.
    act(() => {
      useMyChannelsStore.getState().removeChannel('chan-1');
    });

    expect(await screen.findByText('You were removed from this channel')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'engineering' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /back to channels/i }));

    expect(await screen.findByText('Channels list page')).toBeInTheDocument();
    expect(useMyChannelsStore.getState().removedChannelId).toBeNull();
  });
});
