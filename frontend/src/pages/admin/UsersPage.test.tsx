import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UsersPage } from './UsersPage';
import * as adminApi from '../../api/adminApi';
import { ApiError } from '../../api/problem';

vi.mock('../../api/adminApi');

const ACTIVE_ADMIN = {
  id: 'user-1',
  first_name: 'Priya',
  last_name: 'Admin',
  username: 'priya',
  email: 'priya@example.com',
  role: 'system_admin' as const,
  is_active: true,
  last_seen: '2026-07-08T00:00:00.000Z',
};

const INACTIVE_USER = {
  id: 'user-2',
  first_name: 'Maya',
  last_name: 'Member',
  username: 'maya',
  email: 'maya@example.com',
  role: 'user' as const,
  is_active: false,
  last_seen: null,
};

describe('UsersPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows an empty state when there are no users', async () => {
    vi.mocked(adminApi.listAdminUsers).mockResolvedValue({ items: [], next_cursor: null });

    render(<UsersPage />);

    expect(await screen.findByText('No users yet.')).toBeInTheDocument();
  });

  it('lists users including deactivated ones, with a Never last-seen fallback', async () => {
    vi.mocked(adminApi.listAdminUsers).mockResolvedValue({
      items: [ACTIVE_ADMIN, INACTIVE_USER],
      next_cursor: null,
    });

    render(<UsersPage />);

    expect(await screen.findByText('priya@example.com')).toBeInTheDocument();
    expect(screen.getByText('maya@example.com')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();
    expect(screen.getByText('Never')).toBeInTheDocument();
  });

  it('requires explicit confirmation before deactivating a user', async () => {
    vi.mocked(adminApi.listAdminUsers).mockResolvedValue({ items: [ACTIVE_ADMIN], next_cursor: null });
    vi.mocked(adminApi.deactivateUser).mockResolvedValue({ id: ACTIVE_ADMIN.id, is_active: false });

    const user = userEvent.setup();
    render(<UsersPage />);

    const deactivateButton = await screen.findByRole('button', { name: /^deactivate$/i });
    await user.click(deactivateButton);

    // No API call yet — only the confirmation affordance appears.
    expect(adminApi.deactivateUser).not.toHaveBeenCalled();
    expect(screen.getByText(/deactivate this user\?/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => {
      expect(adminApi.deactivateUser).toHaveBeenCalledWith(ACTIVE_ADMIN.id);
    });
  });

  it('surfaces the last-active-admin 409 with the exact spec copy', async () => {
    vi.mocked(adminApi.listAdminUsers).mockResolvedValue({ items: [ACTIVE_ADMIN], next_cursor: null });
    vi.mocked(adminApi.deactivateUser).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'Cannot deactivate the last active System Admin.',
        instance: '/v1/admin/users/user-1/deactivate',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    render(<UsersPage />);

    await user.click(await screen.findByRole('button', { name: /^deactivate$/i }));
    await user.click(screen.getByRole('button', { name: /^confirm$/i }));

    expect(
      await screen.findByText('The workspace must keep at least one active admin.'),
    ).toBeInTheDocument();
  });

  it('reactivates a deactivated user without a confirmation step', async () => {
    vi.mocked(adminApi.listAdminUsers).mockResolvedValue({ items: [INACTIVE_USER], next_cursor: null });
    vi.mocked(adminApi.reactivateUser).mockResolvedValue({ id: INACTIVE_USER.id, is_active: true });

    const user = userEvent.setup();
    render(<UsersPage />);

    await user.click(await screen.findByRole('button', { name: /^reactivate$/i }));

    await waitFor(() => {
      expect(adminApi.reactivateUser).toHaveBeenCalledWith(INACTIVE_USER.id);
    });
    expect(await screen.findByText('Active')).toBeInTheDocument();
  });
});
