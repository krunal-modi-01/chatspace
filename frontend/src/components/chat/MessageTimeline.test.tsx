import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ChannelMemberSummary, Message } from '../../api/types';
import { MessageTimeline } from './MessageTimeline';

const OWN_ID = '01J0ME00000000000000000000';

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

function makeMember(overrides: Partial<ChannelMemberSummary> = {}): ChannelMemberSummary {
  return {
    user_id: '01J0SENDER00000000000000000',
    username: 'grace',
    first_name: 'Grace',
    last_name: 'Hopper',
    avatar_url: null,
    role: 'member',
    joined_at: '2026-06-01T00:00:00.000Z',
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

  it('renders the member display name and initials badge when identity data is available', () => {
    const members = new Map([[makeMember().user_id, makeMember()]]);
    render(<MessageTimeline messages={[makeMessage({ id: '01J8AAAA' })]} members={members} />);

    expect(screen.getByText('Grace Hopper')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Grace Hopper' })).toHaveTextContent('GH');
  });

  it('falls back to the raw sender_id when no member data is available', () => {
    render(<MessageTimeline messages={[makeMessage({ id: '01J8AAAA' })]} />);
    expect(screen.getByText('01J0SENDER00000000000000000')).toBeInTheDocument();
  });

  it('shows edit/delete affordances only for the current user’s own messages', () => {
    render(
      <MessageTimeline
        messages={[
          makeMessage({ id: '01J8AAAA', sender_id: OWN_ID }),
          makeMessage({ id: '01J8BBBB', sender_id: 'someone-else' }),
        ]}
        currentUserId={OWN_ID}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Delete' })).toHaveLength(1);
  });

  it('edits a message: shows a draft textarea, saves, and exits edit mode on success', async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn().mockResolvedValue(undefined);
    render(
      <MessageTimeline
        messages={[makeMessage({ id: '01J8AAAA', sender_id: OWN_ID, content: 'v1' })]}
        currentUserId={OWN_ID}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    const textbox = screen.getByRole('textbox', { name: 'Edit message' });
    await user.clear(textbox);
    await user.type(textbox, 'v2');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onEdit).toHaveBeenCalledWith('01J8AAAA', 'v2'));
    await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Edit message' })).not.toBeInTheDocument());
  });

  it('shows an inline error and stays in edit mode when the edit is rejected', async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn().mockRejectedValue(new Error('already deleted'));
    render(
      <MessageTimeline
        messages={[makeMessage({ id: '01J8AAAA', sender_id: OWN_ID, content: 'v1' })]}
        currentUserId={OWN_ID}
        onEdit={onEdit}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Edit' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('already deleted'));
    expect(screen.getByRole('textbox', { name: 'Edit message' })).toBeInTheDocument();
  });

  it('deletes a message behind a confirm step', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <MessageTimeline
        messages={[makeMessage({ id: '01J8AAAA', sender_id: OWN_ID })]}
        currentUserId={OWN_ID}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onDelete).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('01J8AAAA'));
  });

  it('clears a failed-delete error when the confirmation is canceled', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn().mockRejectedValue(new Error('Failed to delete message.'));
    render(
      <MessageTimeline
        messages={[makeMessage({ id: '01J8AAAA', sender_id: OWN_ID })]}
        currentUserId={OWN_ID}
        onDelete={onDelete}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Failed to delete message.'));

    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
