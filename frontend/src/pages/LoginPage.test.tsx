import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LoginPage } from './LoginPage';
import * as authApi from '../api/authApi';
import { ApiError } from '../api/problem';

vi.mock('../api/authApi');

// Non-secret fixtures — never real credentials.
const FIXTURE_EMAIL = 'alice@example.com';
const FIXTURE_PASSWORD = ['fixture', 'login', 'pw'].join('-');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/password-reset" element={<div>Password reset page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function problem(status: number, overrides: Record<string, unknown> = {}): ApiError {
  return new ApiError({
    type: `https://chatspace.example/problems/example-${status}`,
    title: 'Example',
    status,
    detail: 'Example detail',
    instance: '/v1/auth/login',
    correlation_id: '01J000EXAMPLE',
    ...overrides,
  });
}

async function submitLogin() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/email/i), FIXTURE_EMAIL);
  await user.type(screen.getByLabelText(/password/i), FIXTURE_PASSWORD);
  await user.click(screen.getByRole('button', { name: /sign in/i }));
}

describe('LoginPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows a specific message + reset link for the must-change-password 403', async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      problem(403, {
        type: 'https://chatspace.example/problems/must-change-password',
        title: 'Password change required',
        detail: 'Your password must be changed before you can log in.',
      }),
    );

    renderAt('/login');
    await submitLogin();

    expect(
      await screen.findByText(/your password must be changed before you can log in/i),
    ).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /reset your password/i });
    expect(link).toHaveAttribute('href', '/password-reset');
    expect(screen.queryByText('Example detail')).not.toBeInTheDocument();
  });

  it('surfaces the generic banner for a 403 deactivated-account error, unchanged', async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      problem(403, {
        type: 'https://chatspace.example/problems/account-deactivated',
        title: 'Account deactivated',
        detail: 'This account has been deactivated.',
      }),
    );

    renderAt('/login');
    await submitLogin();

    expect(await screen.findByText('This account has been deactivated.')).toBeInTheDocument();
    expect(
      screen.queryByText(/your password must be changed before you can log in/i),
    ).not.toBeInTheDocument();
  });

  it('surfaces the generic banner for a 401 invalid-credentials error, unchanged', async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      problem(401, {
        type: 'https://chatspace.example/problems/unauthorized',
        title: 'Unauthorized',
        detail: 'Invalid email or password.',
      }),
    );

    renderAt('/login');
    await submitLogin();

    expect(await screen.findByText('Invalid email or password.')).toBeInTheDocument();
  });
});
