import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { Message } from '../../api/types';
import { MessageTimeline } from './MessageTimeline';

function makeMessage(overrides: Partial<Message> & { id: string }): Message {
  return {
    channel_id: '01J0CHANNEL0000000000000000',
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: 'hello there',
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

describe('MessageTimeline', () => {
  it('renders an empty state with no messages', () => {
    render(<MessageTimeline messages={[]} />);
    expect(screen.getByText(/no messages yet/i)).toBeInTheDocument();
  });

  it('renders message content and an accessible live-region list', () => {
    render(<MessageTimeline messages={[makeMessage({ id: '01J8AAAA', content: 'shipping now' })]} />);

    expect(screen.getByRole('log')).toBeInTheDocument();
    expect(screen.getByText('shipping now')).toBeInTheDocument();
  });

  it('marks an edited message without showing it as deleted', () => {
    render(
      <MessageTimeline
        messages={[
          makeMessage({ id: '01J8AAAA', content: 'fixed typo', edited_at: '2026-07-02T14:35:00.000Z' }),
        ]}
      />,
    );

    expect(screen.getByText('fixed typo')).toBeInTheDocument();
    expect(screen.getByText('(edited)')).toBeInTheDocument();
  });

  it('hides content and shows a placeholder for a deleted message', () => {
    render(
      <MessageTimeline
        messages={[
          makeMessage({ id: '01J8AAAA', content: '', deleted_at: '2026-07-02T14:40:00.000Z' }),
        ]}
      />,
    );

    expect(screen.getByText('This message was deleted.')).toBeInTheDocument();
    expect(screen.queryByText('hello there')).not.toBeInTheDocument();
  });

  it('renders "You" for the current user and the sender id otherwise', () => {
    render(
      <MessageTimeline
        messages={[makeMessage({ id: '01J8AAAA', sender_id: '01J0ME00000000000000000000' })]}
        currentUserId="01J0ME00000000000000000000"
      />,
    );

    expect(screen.getByText('You')).toBeInTheDocument();
  });
});
