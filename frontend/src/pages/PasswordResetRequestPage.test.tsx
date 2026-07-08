import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PasswordResetRequestPage } from './PasswordResetRequestPage';
import * as authApi from '../api/authApi';
import { ApiError } from '../api/problem';

vi.mock('../api/authApi');

const UNIFORM_MESSAGE = 'If an account exists for that email, a reset link has been sent.';

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/password-reset']}>
      <PasswordResetRequestPage />
    </MemoryRouter>,
  );
}

describe('PasswordResetRequestPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows the uniform confirmation message on submit, regardless of account existence', async () => {
    vi.mocked(authApi.requestPasswordReset).mockResolvedValue({ message: UNIFORM_MESSAGE });

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/email/i), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(await screen.findByText(UNIFORM_MESSAGE)).toBeInTheDocument();
    expect(authApi.requestPasswordReset).toHaveBeenCalledWith({ email: 'someone@example.com' });
  });

  it('surfaces a network/server error via the ErrorBanner without hiding the form', async () => {
    vi.mocked(authApi.requestPasswordReset).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/rate-limited',
        title: 'Too many requests',
        status: 429,
        detail: 'Please try again later.',
        instance: '/v1/auth/password-reset',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/email/i), 'someone@example.com');
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(await screen.findByText('Please try again later.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send reset link/i })).toBeInTheDocument();
  });
});
