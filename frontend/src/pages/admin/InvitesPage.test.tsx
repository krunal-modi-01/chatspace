import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InvitesPage } from './InvitesPage';
import * as adminApi from '../../api/adminApi';
import { ApiError } from '../../api/problem';

vi.mock('../../api/adminApi');

const INVITE_FIXTURE = {
  id: 'invite-1',
  email: 'newbie@example.com',
  status: 'pending' as const,
  expiry: '2026-07-15T00:00:00.000Z',
  issued_at: '2026-07-08T00:00:00.000Z',
};

describe('InvitesPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('lists invites and shows an empty state when there are none', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [], next_cursor: null });

    render(<InvitesPage />);

    expect(await screen.findByText('No invites issued yet.')).toBeInTheDocument();
  });

  it('renders outstanding invites with resend/revoke actions on pending rows', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [INVITE_FIXTURE], next_cursor: null });

    render(<InvitesPage />);

    expect(await screen.findByText('newbie@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^resend$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^revoke$/i })).toBeInTheDocument();
  });

  it('rejects a malformed email inline without calling the API', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [], next_cursor: null });

    const user = userEvent.setup();
    render(<InvitesPage />);
    await screen.findByText('No invites issued yet.');

    await user.type(screen.getByLabelText(/^email$/i), 'not-an-email');
    await user.click(screen.getByRole('button', { name: /send invite/i }));

    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument();
    expect(adminApi.issueInvite).not.toHaveBeenCalled();
  });

  it('issues an invite and refreshes the list', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [], next_cursor: null });
    vi.mocked(adminApi.issueInvite).mockResolvedValue({
      id: 'invite-2',
      email: 'friend@example.com',
      status: 'pending',
      expiry: '2026-07-15T00:00:00.000Z',
    });

    const user = userEvent.setup();
    render(<InvitesPage />);
    await screen.findByText('No invites issued yet.');

    await user.type(screen.getByLabelText(/^email$/i), 'friend@example.com');
    await user.click(screen.getByRole('button', { name: /send invite/i }));

    await waitFor(() => {
      expect(adminApi.issueInvite).toHaveBeenCalledWith({ email: 'friend@example.com' });
    });
    expect(adminApi.listInvites).toHaveBeenCalledTimes(2);
  });

  it('surfaces a 409 already-registered error with the exact spec copy', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [], next_cursor: null });
    vi.mocked(adminApi.issueInvite).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'Email already registered.',
        instance: '/v1/invites',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    render(<InvitesPage />);
    await screen.findByText('No invites issued yet.');

    await user.type(screen.getByLabelText(/^email$/i), 'existing@example.com');
    await user.click(screen.getByRole('button', { name: /send invite/i }));

    expect(await screen.findByText('This email already has an account.')).toBeInTheDocument();
  });

  it('surfaces a 502 delivery error with the exact spec copy', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [], next_cursor: null });
    vi.mocked(adminApi.issueInvite).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/bad-gateway',
        title: 'Bad gateway',
        status: 502,
        detail: 'SMTP unreachable.',
        instance: '/v1/invites',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    render(<InvitesPage />);
    await screen.findByText('No invites issued yet.');

    await user.type(screen.getByLabelText(/^email$/i), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: /send invite/i }));

    expect(await screen.findByText("Invite couldn't be delivered — try again.")).toBeInTheDocument();
  });

  it('revokes a pending invite and removes it from the list', async () => {
    vi.mocked(adminApi.listInvites).mockResolvedValue({ items: [INVITE_FIXTURE], next_cursor: null });
    vi.mocked(adminApi.revokeInvite).mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<InvitesPage />);

    const revokeButton = await screen.findByRole('button', { name: /^revoke$/i });
    await user.click(revokeButton);

    await waitFor(() => {
      expect(adminApi.revokeInvite).toHaveBeenCalledWith('invite-1');
    });
    await waitFor(() => {
      expect(screen.queryByText('newbie@example.com')).not.toBeInTheDocument();
    });
  });
});
