import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PasswordResetConfirmPage } from './PasswordResetConfirmPage';
import * as authApi from '../api/authApi';
import { ApiError } from '../api/problem';

vi.mock('../api/authApi');

// Non-secret fixtures — never real credentials.
const FIXTURE_NEW_PASSWORD = ['fixture', 'new', 'pw', '9'].join('-');
const FIXTURE_RESET_TOKEN = ['fixture', 'reset', 'token'].join('-');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/password-reset/confirm" element={<PasswordResetConfirmPage />} />
        <Route path="/login" element={<div>Login page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PasswordResetConfirmPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders a link-expired message when there is no token in the URL', () => {
    renderAt('/password-reset/confirm');

    expect(screen.getByText(/reset link expired/i)).toBeInTheDocument();
  });

  it('submits the new password with the token and redirects to login on success', async () => {
    vi.mocked(authApi.confirmPasswordReset).mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderAt(`/password-reset/confirm?token=${FIXTURE_RESET_TOKEN}`);

    await user.type(screen.getByLabelText(/new password/i), FIXTURE_NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /set new password/i }));

    await waitFor(() => {
      expect(authApi.confirmPasswordReset).toHaveBeenCalledWith({
        reset_token: FIXTURE_RESET_TOKEN,
        new_password: FIXTURE_NEW_PASSWORD,
      });
    });
    expect(await screen.findByText('Login page')).toBeInTheDocument();
  });

  it('renders the link-expired state on a 410 from the confirm call', async () => {
    vi.mocked(authApi.confirmPasswordReset).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/gone',
        title: 'Gone',
        status: 410,
        detail: 'Reset token is expired, already used, or no longer valid.',
        instance: '/v1/auth/password-reset/confirm',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderAt(`/password-reset/confirm?token=${FIXTURE_RESET_TOKEN}`);

    await user.type(screen.getByLabelText(/new password/i), FIXTURE_NEW_PASSWORD);
    await user.click(screen.getByRole('button', { name: /set new password/i }));

    expect(await screen.findByText(/reset link expired/i)).toBeInTheDocument();
  });
});
