import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useAuthStore } from './authStore';
import { useMyChannelsStore } from './myChannelsStore';

const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

describe('authStore.clearSession', () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: {
        id: 'user-1',
        username: 'alice',
        email: 'alice@example.com',
        first_name: 'Alice',
        last_name: 'Anderson',
        avatar_url: null,
        role: 'user',
        is_active: true,
        last_seen: null,
        created_at: '2026-07-01T00:00:00.000Z',
      },
      isBootstrapping: false,
    });
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('clears the auth session', () => {
    useAuthStore.getState().clearSession();

    const state = useAuthStore.getState();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(state.user).toBeNull();
  });

  it('also resets the shared myChannelsStore, so a subsequent login in the same tab never renders a previous account’s private channels (security: cross-account data leakage on shared/kiosk browsers)', () => {
    useMyChannelsStore.setState({
      channels: [
        {
          id: 'private-channel',
          name: 'leadership',
          is_private: true,
          created_by: 'user-1',
          created_at: '2026-07-01T00:00:00.000Z',
          member_count: 3,
          my_role: 'admin',
        },
      ],
      isLoading: false,
      error: null,
      viewedChannelId: 'private-channel',
      removedChannelId: null,
    });

    useAuthStore.getState().clearSession();

    expect(useMyChannelsStore.getState()).toMatchObject({
      channels: [],
      isLoading: true,
      error: null,
      viewedChannelId: null,
      removedChannelId: null,
    });
  });
});
