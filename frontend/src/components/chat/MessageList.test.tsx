import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../../api/types';

const { useAuthMock, useChannelMembersMock, useMessageHistoryMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  useChannelMembersMock: vi.fn(),
  useMessageHistoryMock: vi.fn(),
}));

vi.mock('../../hooks/useAuth', () => ({ useAuth: useAuthMock }));
vi.mock('../../hooks/useChannelMembers', () => ({ useChannelMembers: useChannelMembersMock }));
vi.mock('../../hooks/useMessageHistory', () => ({ useMessageHistory: useMessageHistoryMock }));

const { MessageList } = await import('./MessageList');

function msg(id: string, overrides: Partial<Message> = {}): Message {
  return {
    id,
    channel_id: '01J0CHANNEL0000000000000000',
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: `content-${id}`,
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function baseHistoryResult(overrides: Partial<ReturnType<typeof useMessageHistoryMock>> = {}) {
  return {
    messages: [],
    pendingSends: [],
    isLoadingInitial: false,
    isLoadingOlder: false,
    hasMoreOlder: false,
    historyError: null,
    actionError: null,
    sendMessage: vi.fn(),
    retrySend: vi.fn(),
    discardFailedSend: vi.fn(),
    loadOlder: vi.fn(),
    retryInitialLoad: vi.fn(),
    editMessage: vi.fn(),
    deleteMessage: vi.fn(),
    ...overrides,
  };
}

describe('MessageList', () => {
  beforeEach(() => {
    useAuthMock.mockReturnValue({ user: { id: '01J0ME00000000000000000000' } });
    useChannelMembersMock.mockReturnValue({ membersById: new Map(), isLoading: false, error: null });
  });

  it('shows a loading state while the initial history page loads', () => {
    useMessageHistoryMock.mockReturnValue(baseHistoryResult({ isLoadingInitial: true }));
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);
    expect(screen.getByRole('status')).toHaveTextContent(/loading messages/i);
  });

  it('shows a history error with a retry action', async () => {
    const retryInitialLoad = vi.fn();
    useMessageHistoryMock.mockReturnValue(baseHistoryResult({ historyError: new Error('down'), retryInitialLoad }));
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    expect(screen.getByRole('alert')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }));
    expect(retryInitialLoad).toHaveBeenCalledTimes(1);
  });

  it('renders confirmed messages and a "load older" button when more history is available', async () => {
    const loadOlder = vi.fn();
    useMessageHistoryMock.mockReturnValue(
      baseHistoryResult({ messages: [msg('01J8AAAA', { content: 'hi' })], hasMoreOlder: true, loadOlder }),
    );
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    expect(screen.getByText('hi')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Load older messages' }));
    expect(loadOlder).toHaveBeenCalledTimes(1);
  });

  it('renders a pending (optimistic) send with a Sending… status', () => {
    useMessageHistoryMock.mockReturnValue(
      baseHistoryResult({
        pendingSends: [
          { id: 'temp-1', content: 'on its way', idempotencyKey: 'k1', status: 'sending', createdAt: '', error: null },
        ],
      }),
    );
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    expect(screen.getByText('on its way')).toBeInTheDocument();
    expect(screen.getByText('Sending…')).toBeInTheDocument();
  });

  it('renders a failed send with retry/discard actions', async () => {
    const retrySend = vi.fn();
    const discardFailedSend = vi.fn();
    useMessageHistoryMock.mockReturnValue(
      baseHistoryResult({
        pendingSends: [
          {
            id: 'temp-1',
            content: 'oops',
            idempotencyKey: 'k1',
            status: 'failed',
            createdAt: '',
            error: 'Failed to send message.',
          },
        ],
        retrySend,
        discardFailedSend,
      }),
    );
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retrySend).toHaveBeenCalledWith('temp-1');

    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect(discardFailedSend).toHaveBeenCalledWith('temp-1');
  });

  it('wires the composer to sendMessage', async () => {
    const sendMessage = vi.fn();
    useMessageHistoryMock.mockReturnValue(baseHistoryResult({ sendMessage }));
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    const user = userEvent.setup();
    await user.type(screen.getByRole('textbox'), 'hello{Enter}');
    expect(sendMessage).toHaveBeenCalledWith('hello');
  });

  it('preserves scroll position when older messages are prepended (no scroll-jump)', async () => {
    const loadOlder = vi.fn().mockResolvedValue(undefined);
    const initialMessages = [msg('01J8AAAA', { content: 'first' })];
    useMessageHistoryMock.mockReturnValue(
      baseHistoryResult({ messages: initialMessages, hasMoreOlder: true, loadOlder }),
    );

    const { container, rerender } = render(<MessageList channelId="01J0CHANNEL0000000000000000" />);
    const scrollEl = container.querySelector('.overflow-y-auto') as HTMLDivElement;
    expect(scrollEl).not.toBeNull();

    Object.defineProperty(scrollEl, 'scrollHeight', { value: 500, configurable: true });
    scrollEl.scrollTop = 50;

    await userEvent.setup().click(screen.getByRole('button', { name: 'Load older messages' }));
    expect(loadOlder).toHaveBeenCalledTimes(1);

    // Simulate `loadOlder` having resolved and prepended an older batch,
    // growing the scrollable content above the previously-visible messages.
    Object.defineProperty(scrollEl, 'scrollHeight', { value: 800, configurable: true });
    useMessageHistoryMock.mockReturnValue(
      baseHistoryResult({
        messages: [msg('01J8ZZZZ', { content: 'older' }), ...initialMessages],
        hasMoreOlder: false,
        loadOlder,
      }),
    );
    rerender(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    // scrollTop should shift by exactly the added height so the
    // previously-visible content stays in the same visual position.
    expect(scrollEl.scrollTop).toBe(50 + (800 - 500));
  });

  it('shows a warning banner when member identity data failed to load', () => {
    useChannelMembersMock.mockReturnValue({ membersById: new Map(), isLoading: false, error: new Error('nope') });
    useMessageHistoryMock.mockReturnValue(baseHistoryResult());
    render(<MessageList channelId="01J0CHANNEL0000000000000000" />);

    expect(screen.getByText(/could not load member details/i)).toBeInTheDocument();
  });
});
