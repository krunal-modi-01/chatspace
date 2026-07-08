import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RegisterPage } from './RegisterPage';
import * as authApi from '../api/authApi';
import { ApiError } from '../api/problem';

vi.mock('../api/authApi');

// Non-secret fixture — never a real credential.
const FIXTURE_PASSWORD = ['fixture', 'pw', '123'].join('-');
const FIXTURE_INVITE_TOKEN = ['good', 'invite', 'fixture'].join('-');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/login" element={<div>Login page</div>} />
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
    instance: '/v1/auth/register',
    correlation_id: '01J000EXAMPLE',
    ...overrides,
  });
}

describe('RegisterPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('renders an invalid-invite message when there is no token', async () => {
    renderAt('/register');

    await waitFor(() => {
      expect(screen.getByText(/invite link is no longer valid/i)).toBeInTheDocument();
    });
  });

  it('renders an invalid-invite message on a 410 from the prefill call', async () => {
    vi.mocked(authApi.fetchInvite).mockRejectedValue(problem(410));

    renderAt('/register?token=stale-token');

    await waitFor(() => {
      expect(screen.getByText(/invite link is no longer valid/i)).toBeInTheDocument();
    });
  });

  it('pre-fills and locks the email, then submits registration and redirects to login', async () => {
    vi.mocked(authApi.fetchInvite).mockResolvedValue({
      email: 'invited@example.com',
      expiry: '2026-07-14T00:00:00.000Z',
    });
    vi.mocked(authApi.register).mockResolvedValue({
      id: 'user-1',
      username: 'newuser',
      email: 'invited@example.com',
      first_name: 'New',
      last_name: 'User',
      avatar_url: null,
      role: 'user',
      created_at: '2026-07-07T00:00:00.000Z',
    });

    const user = userEvent.setup();
    renderAt(`/register?token=${FIXTURE_INVITE_TOKEN}`);

    const emailInput = await screen.findByLabelText(/email/i);
    expect(emailInput).toHaveValue('invited@example.com');
    expect(emailInput).toBeDisabled();

    await user.type(screen.getByLabelText(/username/i), 'newuser');
    await user.type(screen.getByLabelText(/first name/i), 'New');
    await user.type(screen.getByLabelText(/last name/i), 'User');
    await user.type(screen.getByLabelText(/^password/i), FIXTURE_PASSWORD);
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await waitFor(() => {
      expect(authApi.register).toHaveBeenCalledWith({
        invite_token: FIXTURE_INVITE_TOKEN,
        username: 'newuser',
        first_name: 'New',
        last_name: 'User',
        password: FIXTURE_PASSWORD,
        avatar_url: null,
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Login page')).toBeInTheDocument();
    });
  });

  it('surfaces a 409 duplicate-identity error without redirecting', async () => {
    vi.mocked(authApi.fetchInvite).mockResolvedValue({
      email: 'invited@example.com',
      expiry: '2026-07-14T00:00:00.000Z',
    });
    vi.mocked(authApi.register).mockRejectedValue(
      problem(409, { detail: 'This username or email is already registered.' }),
    );

    const user = userEvent.setup();
    renderAt(`/register?token=${FIXTURE_INVITE_TOKEN}`);

    await screen.findByLabelText(/email/i);
    await user.type(screen.getByLabelText(/username/i), 'newuser');
    await user.type(screen.getByLabelText(/first name/i), 'New');
    await user.type(screen.getByLabelText(/last name/i), 'User');
    await user.type(screen.getByLabelText(/^password/i), FIXTURE_PASSWORD);
    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByText('This username or email is already registered.')).toBeInTheDocument();
  });
});
