import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchChannelMembers } from './channelsApi';
import { useAuthStore } from '../store/authStore';

// Non-secret placeholder — see `messagesApi.test.ts` for the convention.
const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

describe('channelsApi', () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: ['refresh', 'token', 'fixture'].join('-'),
      user: null,
      isBootstrapping: false,
    });
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('requests the channel member list and returns items/total', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          {
            user_id: '01J0USER0000000000000000000',
            username: 'ada',
            first_name: 'Ada',
            last_name: 'Lovelace',
            avatar_url: null,
            role: 'member',
            joined_at: '2026-07-01T00:00:00.000Z',
          },
        ],
        total: 1,
      }),
    );

    const page = await fetchChannelMembers('01J0CHANNEL0000000000000000', { limit: 100, offset: 0 });

    expect(page.total).toBe(1);
    expect(page.items[0].username).toBe('ada');
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/channels/01J0CHANNEL0000000000000000/members');
    expect(String(url)).toContain('limit=100');
    expect(String(url)).toContain('offset=0');
  });
});
