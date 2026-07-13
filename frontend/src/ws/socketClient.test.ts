import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/problem';
import type { ConversationTarget } from '../api/types';
import { WsCloseCode } from './closeCodes';
import type { SocketClientOptions, WebSocketLike } from './socketClient';
import { ReconnectingSocket } from './socketClient';

class FakeWebSocket implements WebSocketLike {
  static instances: FakeWebSocket[] = [];

  readyState = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  closeCalls: Array<number | undefined> = [];
  url: string;
  protocols: string[] | undefined;

  constructor(url: string, protocols?: string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number): void {
    this.closeCalls.push(code);
    this.readyState = 3; // CLOSED
    this.onclose?.({ code: code ?? 1000 });
  }

  // --- test helpers, not part of WebSocketLike ---

  simulateOpen(): void {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  simulateMessage(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  simulateServerClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: '01J0CHANNEL0000000000000000' };

function lastSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) throw new Error('no FakeWebSocket instance created');
  return socket;
}

describe('ReconnectingSocket', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeClient(overrides: Partial<SocketClientOptions> = {}) {
    const statuses: string[] = [];
    const frames: unknown[] = [];
    const fatals: string[] = [];
    const refreshAccessToken = vi.fn().mockResolvedValue('new-token');

    const client = new ReconnectingSocket({
      buildUrl: () => 'wss://example.test/v1/ws',
      getAccessToken: () => 'initial-token',
      refreshAccessToken,
      webSocketFactory: (url, protocols) => new FakeWebSocket(url, protocols),
      onStatusChange: (s) => statuses.push(s),
      onFrame: (f) => frames.push(f),
      onFatal: (r) => fatals.push(r),
      heartbeatIntervalMs: 1000,
      backoff: { initialMs: 100, maxMs: 400, factor: 2 },
      ...overrides,
    });

    return { client, statuses, frames, fatals, refreshAccessToken };
  }

  it('connects with no token in the URL, offering it via the bearer sub-protocol instead', () => {
    const { client } = makeClient();
    client.connect();
    expect(lastSocket().url).toBe('wss://example.test/v1/ws');
    expect(lastSocket().protocols).toEqual(['bearer', 'initial-token']);
  });

  it('sends a join frame for a joined conversation once open, and re-sends it on reconnect', () => {
    const { client } = makeClient();
    client.connect();
    client.join(CHANNEL);

    const first = lastSocket();
    first.simulateOpen();
    expect(first.sent).toEqual([JSON.stringify({ type: 'join', conversation: CHANNEL })]);

    // Drop with a transient code -> reconnect -> re-join automatically.
    first.simulateServerClose(WsCloseCode.HEARTBEAT_TIMEOUT);
    vi.advanceTimersByTime(100);

    const second = lastSocket();
    expect(second).not.toBe(first);
    second.simulateOpen();
    expect(second.sent).toEqual([JSON.stringify({ type: 'join', conversation: CHANNEL })]);
  });

  it('surfaces a well-formed server frame via onFrame', () => {
    const { client, frames } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateMessage({ type: 'message.created', conversation: CHANNEL, data: { id: '01J8AAAA' } });

    expect(frames).toEqual([{ type: 'message.created', conversation: CHANNEL, data: { id: '01J8AAAA' } }]);
  });

  it('tolerates an unrecognized frame type (open enum) without throwing', () => {
    const { client, frames } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    expect(() => socket.simulateMessage({ type: 'some.future.event', data: {} })).not.toThrow();
    expect(frames).toEqual([{ type: 'some.future.event', data: {} }]);
  });

  it('ignores a malformed (non-JSON) message instead of crashing', () => {
    const { client, frames } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();
    socket.onmessage?.({ data: 'not json' });

    expect(frames).toEqual([]);
  });

  it('on 4402 (token-expired), refreshes the access token then reconnects', async () => {
    const { client, statuses, refreshAccessToken } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));

    expect(statuses).toContain('reconnecting');
  });

  it('on a transient refresh failure (e.g. network error), backs off and retries instead of going fatal', async () => {
    const refreshAccessToken = vi.fn().mockRejectedValue(new Error('network down'));
    const { client, fatals, statuses } = makeClient({ refreshAccessToken });
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));

    // Not fatal — the refresh call itself just failed transiently.
    expect(fatals).toEqual([]);
    expect(client.getStatus()).toBe('reconnecting');

    vi.advanceTimersByTime(100);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    expect(statuses).toContain('reconnecting');
  });

  it('escalates to fatal after repeated refresh-then-immediate-reclose cycles that never stabilize', async () => {
    const { client, fatals, refreshAccessToken } = makeClient({
      maxConsecutiveRefreshCycles: 2,
      minStableConnectionMs: 10_000,
    });
    client.connect();
    let socket = lastSocket();
    socket.simulateOpen();

    // Cycle 1 — first refresh-and-reconnect since start: reconnects immediately.
    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    socket = lastSocket();
    socket.simulateOpen();

    // Cycle 2 — closes again before the connection ever stabilizes: this is
    // a repeat cycle, so it backs off (100ms per the test backoff config)
    // before reopening, rather than reconnecting instantly.
    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(2));
    expect(FakeWebSocket.instances.length).toBe(2); // not yet reopened
    vi.advanceTimersByTime(100);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(3));
    socket = lastSocket();
    socket.simulateOpen();

    // Cycle 3 — exceeds `maxConsecutiveRefreshCycles` (2): escalate to fatal
    // instead of retrying again.
    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(3));
    await vi.waitFor(() => expect(fatals).toEqual(['auth-failed']));
    expect(client.getStatus()).toBe('closed');

    vi.advanceTimersByTime(20_000);
    expect(FakeWebSocket.instances.length).toBe(3); // no further reconnect attempt
  });

  it('resets the consecutive-refresh-cycle counter once a connection stays open past minStableConnectionMs', async () => {
    const { client, fatals } = makeClient({ maxConsecutiveRefreshCycles: 1, minStableConnectionMs: 500 });
    client.connect();
    let socket = lastSocket();
    socket.simulateOpen();

    // Cycle 1 (count -> 1, at the cap but not exceeding it): reconnects immediately.
    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
    socket = lastSocket();
    socket.simulateOpen();

    // Stays open long enough to be considered stable — the cycle counter
    // resets back to 0.
    vi.advanceTimersByTime(500);

    // An unrelated, later cycle is again treated as "cycle 1" (immediate
    // reopen, no fatal) rather than being counted against the earlier one.
    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(3));
    expect(fatals).toEqual([]);
  });

  it('on a definitive refresh rejection (401/403 from /auth/refresh), goes fatal without reconnecting', async () => {
    const refreshAccessToken = vi.fn().mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/unauthenticated',
        title: 'Not authenticated',
        status: 401,
        detail: 'Refresh token is invalid.',
        instance: '/auth/refresh',
        correlation_id: 'test',
      }),
    );
    const { client, fatals } = makeClient({ refreshAccessToken });
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));

    expect(fatals).toEqual(['auth-failed']);
    expect(client.getStatus()).toBe('closed');
    vi.advanceTimersByTime(5000);
    expect(FakeWebSocket.instances.length).toBe(1); // no reconnect attempt
  });

  it('a close before the connection ever reached open is treated as ambiguous-auth and refreshes eagerly', async () => {
    // Backend gap: a pre-accept 4401 close is delivered to the browser as
    // plain abnormal closure 1006, never as a real close code, because
    // `websocket.close()` is called before `websocket.accept()` server-side.
    const { client, refreshAccessToken } = makeClient();
    client.connect();
    const socket = lastSocket();

    socket.simulateServerClose(1006); // never called simulateOpen()

    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));
  });

  it('does not treat an already-open connection dropping with an undocumented code as ambiguous-auth', () => {
    const { client, refreshAccessToken } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(1006);

    // Reached `open` before this close — ordinary backoff reconnect, no
    // eager refresh.
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(client.getStatus()).toBe('reconnecting');
  });

  it('a manual disconnect() during an in-flight 4402 refresh suppresses the pending reopen', async () => {
    let resolveRefresh: (token: string) => void = () => {};
    const refreshAccessToken = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolveRefresh = resolve;
        }),
    );
    const { client } = makeClient({ refreshAccessToken });
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.TOKEN_EXPIRED);
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));

    client.disconnect();
    resolveRefresh('new-token');
    await vi.waitFor(() => expect(refreshAccessToken).toHaveBeenCalledTimes(1));

    expect(FakeWebSocket.instances.length).toBe(1); // no new socket reopened
  });

  it('on 4403 (token-revoked), stops permanently and reports a fatal reason without reconnecting', () => {
    const { client, fatals } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.TOKEN_REVOKED);
    vi.advanceTimersByTime(5000);

    expect(fatals).toEqual(['revoked']);
    expect(client.getStatus()).toBe('closed');
    expect(FakeWebSocket.instances.length).toBe(1); // no reconnect attempt
  });

  it('on 4404 (user-deactivated), stops permanently', () => {
    const { client, fatals } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.USER_DEACTIVATED);

    expect(fatals).toEqual(['deactivated']);
    expect(client.getStatus()).toBe('closed');
  });

  it('client-initiated disconnect (normal closure) does not trigger a reconnect', () => {
    const { client } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    client.disconnect();
    vi.advanceTimersByTime(5000);

    expect(FakeWebSocket.instances.length).toBe(1);
    expect(client.getStatus()).toBe('closed');
  });

  it('reconnects with exponential backoff on an unknown/undocumented close code', () => {
    const { client, statuses } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(4999); // undocumented/future code
    expect(statuses.at(-1)).toBe('reconnecting');
    expect(FakeWebSocket.instances.length).toBe(1);

    vi.advanceTimersByTime(99);
    expect(FakeWebSocket.instances.length).toBe(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances.length).toBe(2);
  });

  it('sends periodic ping heartbeats while open', () => {
    const { client } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    vi.advanceTimersByTime(1000);
    expect(socket.sent).toContain(JSON.stringify({ type: 'ping' }));
  });

  it('destroy() suppresses any pending reconnect', () => {
    const { client } = makeClient();
    client.connect();
    const socket = lastSocket();
    socket.simulateOpen();

    socket.simulateServerClose(WsCloseCode.HEARTBEAT_TIMEOUT);
    client.destroy();
    vi.advanceTimersByTime(5000);

    expect(FakeWebSocket.instances.length).toBe(1);
  });
});
