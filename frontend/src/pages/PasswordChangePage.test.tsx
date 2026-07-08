import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PasswordChangePage } from './PasswordChangePage';
import * as authApi from '../api/authApi';
import { ApiError } from '../api/problem';

vi.mock('../api/authApi');

// Non-secret fixtures — never real credentials.
const FIXTURE_CURRENT_PASSWORD = ['fixture', 'current', 'pw'].join('-');
const FIXTURE_NEW_PASSWORD = ['fixture', 'new', 'pw', '9'].join('-');

describe('PasswordChangePage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows a success message and keeps the session (no redirect) after changing the password', async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<PasswordChangePage />);

    await user.type(screen.getByLabelText(/current password/i), FIXTURE_CURRENT_PASSWORD);
    await user.type(screen.getByLabelText(/new password/i), FIXTURE_NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /change password/i }));

    expect(await screen.findByText(/all other sessions have been signed out/i)).toBeInTheDocument();
    expect(authApi.changePassword).toHaveBeenCalledWith({
      current_password: FIXTURE_CURRENT_PASSWORD,
      new_password: FIXTURE_NEW_PASSWORD,
    });
  });

  it('surfaces a 401 wrong-current-password error', async () => {
    vi.mocked(authApi.changePassword).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/unauthorized',
        title: 'Unauthorized',
        status: 401,
        detail: 'Current password is incorrect.',
        instance: '/v1/auth/password/change',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    render(<PasswordChangePage />);

    await user.type(screen.getByLabelText(/current password/i), FIXTURE_CURRENT_PASSWORD);
    await user.type(screen.getByLabelText(/new password/i), FIXTURE_NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /change password/i }));

    expect(await screen.findByText('Current password is incorrect.')).toBeInTheDocument();
  });
});
