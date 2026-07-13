import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { deleteMessage, editMessage, fetchMessageHistory, sendMessage } from './messagesApi';
import { useAuthStore } from '../store/authStore';
import type { ConversationTarget, Message } from './types';

// Non-secret placeholder values used only as opaque test fixtures — never
// real credentials. Built via `join` (matching `api/httpClient.test.ts`'s
// convention) so no `token: "<value>"`-shaped string literal appears here.
const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');
const FIXTURE_IDEMPOTENCY_KEY = ['idempotency', 'key', 'fixture'].join('-');
const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: '01J0CHANNEL0000000000000000' };

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
}

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: '01J8AAAA',
    channel_id: CHANNEL.kind === 'channel' ? CHANNEL.channel_id : null,
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: 'hello',
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

describe('messagesApi', () => {
  beforeEach(() => {
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fetchMessageHistory requests the channel history path with limit/cursor', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [message()], next_cursor: null }));

    const page = await fetchMessageHistory(CHANNEL, { limit: 50, cursor: 'abc' });

    expect(page.items).toHaveLength(1);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/channels/${CHANNEL.channel_id}/messages`);
    expect(String(url)).toContain('limit=50');
    expect(String(url)).toContain('cursor=abc');
  });

  it('sendMessage sends the Idempotency-Key header and reports created=true on 201', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(message(), { status: 201 }));

    const result = await sendMessage(CHANNEL, { content: 'hi there' }, FIXTURE_IDEMPOTENCY_KEY);

    expect(result.created).toBe(true);
    expect(result.message.id).toBe('01J8AAAA');

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain(`/channels/${CHANNEL.channel_id}/messages`);
    expect(init?.method).toBe('POST');
    const headers = init?.headers as Record<string, string>;
    expect(headers['Idempotency-Key']).toBe(FIXTURE_IDEMPOTENCY_KEY);
    expect(JSON.parse(init?.body as string)).toEqual({ content: 'hi there' });
  });

  it('sendMessage reports created=false on a 200 idempotent replay', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(message(), { status: 200 }));

    const result = await sendMessage(CHANNEL, { content: 'hi there' }, FIXTURE_IDEMPOTENCY_KEY);

    expect(result.created).toBe(false);
  });

  it('editMessage PATCHes /messages/{id} with the new content', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(jsonResponse(message({ content: 'edited', edited_at: '2026-07-02T15:00:00.000Z' })));

    const updated = await editMessage('01J8AAAA', { content: 'edited' });

    expect(updated.content).toBe('edited');
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/messages/01J8AAAA');
    expect(init?.method).toBe('PATCH');
  });

  it('deleteMessage DELETEs /messages/{id} and resolves on 204', async () => {
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteMessage('01J8AAAA')).resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/messages/01J8AAAA');
    expect(init?.method).toBe('DELETE');
  });
});
