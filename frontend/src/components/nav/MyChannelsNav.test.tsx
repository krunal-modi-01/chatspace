import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MyChannelsNav } from './MyChannelsNav';
import * as channelsApi from '../../api/channelsApi';

vi.mock('../../api/channelsApi');

function renderNav() {
  return render(
    <MemoryRouter initialEntries={['/channels/chan-1']}>
      <Routes>
        <Route path="/channels/:channelId" element={<MyChannelsNav />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('MyChannelsNav', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows a loading state while the list is fetched', async () => {
    vi.mocked(channelsApi.listMyChannels).mockImplementation(() => new Promise(() => {}));

    renderNav();

    expect(screen.getByRole('status')).toHaveTextContent('Loading your channels…');
  });

  it('shows the "no channels joined" empty state', async () => {
    vi.mocked(channelsApi.listMyChannels).mockResolvedValue({ items: [], next_cursor: null });

    renderNav();

    expect(await screen.findByText("You haven't joined any channels yet.")).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /browse public channels/i })).toBeInTheDocument();
  });

  it('renders an error state on fetch failure', async () => {
    vi.mocked(channelsApi.listMyChannels).mockRejectedValue(new Error('boom'));

    renderNav();

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument();
  });

  it('lists every membership including a private channel with its own role', async () => {
    vi.mocked(channelsApi.listMyChannels).mockResolvedValue({
      items: [
        {
          id: 'chan-1',
          name: 'general',
          is_private: false,
          created_by: 'user-1',
          created_at: '2026-07-01T00:00:00.000Z',
          member_count: 10,
          my_role: 'member',
        },
        {
          id: 'chan-2',
          name: 'leadership',
          is_private: true,
          created_by: 'user-1',
          created_at: '2026-07-02T00:00:00.000Z',
          member_count: 3,
          my_role: 'admin',
        },
      ],
      next_cursor: null,
    });

    renderNav();

    expect(await screen.findByText('general')).toBeInTheDocument();
    expect(screen.getByText('leadership')).toBeInTheDocument();
    expect(screen.getAllByText('Public')).toHaveLength(1);
    expect(screen.getAllByText('Private')).toHaveLength(1);
    expect(screen.getByText('member')).toBeInTheDocument();
    expect(screen.getByText('admin')).toBeInTheDocument();

    const link = screen.getByRole('link', { name: /general/i });
    expect(link).toHaveAttribute('href', '/channels/chan-1');
  });
});
