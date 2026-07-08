import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionsPage } from './SessionsPage';
import * as authApi from '../api/authApi';

vi.mock('../api/authApi');

describe('SessionsPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('lists sessions, labels the current one, and falls back for a null device label', async () => {
    vi.mocked(authApi.listSessions).mockResolvedValue({
      items: [
        {
          session_id: 'session-current',
          created_at: '2026-07-01T00:00:00.000Z',
          last_seen_at: '2026-07-06T00:00:00.000Z',
          device_label: 'Chrome on macOS',
          current: true,
        },
        {
          session_id: 'session-other',
          created_at: '2026-07-02T00:00:00.000Z',
          last_seen_at: null,
          device_label: null,
          current: false,
        },
      ],
    });

    render(<SessionsPage />);

    expect(await screen.findByText('Chrome on macOS')).toBeInTheDocument();
    expect(screen.getByText('This device')).toBeInTheDocument();
    expect(screen.getByText('Unknown device')).toBeInTheDocument();
    // Only the non-current session should offer a revoke action.
    expect(screen.getAllByRole('button', { name: /revoke/i })).toHaveLength(1);
  });

  it('revokes a non-current session and removes it from the list', async () => {
    vi.mocked(authApi.listSessions).mockResolvedValue({
      items: [
        {
          session_id: 'session-other',
          created_at: '2026-07-02T00:00:00.000Z',
          last_seen_at: null,
          device_label: 'Firefox on Linux',
          current: false,
        },
      ],
    });
    vi.mocked(authApi.revokeSession).mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<SessionsPage />);

    const revokeButton = await screen.findByRole('button', { name: /revoke/i });
    await user.click(revokeButton);

    await waitFor(() => {
      expect(authApi.revokeSession).toHaveBeenCalledWith('session-other');
    });
    await waitFor(() => {
      expect(screen.queryByText('Firefox on Linux')).not.toBeInTheDocument();
    });
  });
});
