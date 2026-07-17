import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ChannelMemberSummary } from '../../api/types';
import { TypingIndicator } from './TypingIndicator';

function member(overrides: Partial<ChannelMemberSummary> = {}): ChannelMemberSummary {
  return {
    user_id: 'user-1',
    username: 'alice',
    first_name: 'Alice',
    last_name: 'Doe',
    avatar_url: null,
    role: 'member',
    joined_at: '2026-07-01T00:00:00.000Z',
    ...overrides,
  };
}

describe('TypingIndicator', () => {
  it('renders nothing when nobody is typing', () => {
    const { container } = render(<TypingIndicator userIds={[]} members={new Map()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a single typer by name', () => {
    const members = new Map([['user-1', member()]]);
    render(<TypingIndicator userIds={['user-1']} members={members} />);
    expect(screen.getByText('Alice Doe is typing…')).toBeInTheDocument();
  });

  it('renders two typers joined by "and"', () => {
    const members = new Map([
      ['user-1', member({ user_id: 'user-1', first_name: 'Alice', last_name: 'Doe' })],
      ['user-2', member({ user_id: 'user-2', first_name: 'Bob', last_name: 'Smith' })],
    ]);
    render(<TypingIndicator userIds={['user-1', 'user-2']} members={members} />);
    expect(screen.getByText('Alice Doe and Bob Smith are typing…')).toBeInTheDocument();
  });

  it('collapses three or more typers to a count', () => {
    const members = new Map<string, ChannelMemberSummary>();
    render(<TypingIndicator userIds={['user-1', 'user-2', 'user-3']} members={members} />);
    expect(screen.getByText('3 people are typing…')).toBeInTheDocument();
  });

  it('falls back to "Someone" for a typer not present in the identity map', () => {
    render(<TypingIndicator userIds={['user-unknown']} members={new Map()} />);
    expect(screen.getByText('Someone is typing…')).toBeInTheDocument();
  });

  it('is a polite live region', () => {
    const members = new Map([['user-1', member()]]);
    render(<TypingIndicator userIds={['user-1']} members={members} />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });
});
