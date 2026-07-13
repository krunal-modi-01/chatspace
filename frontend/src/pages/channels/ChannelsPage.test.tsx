import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChannelsPage } from './ChannelsPage';
import * as channelsApi from '../../api/channelsApi';
import { ApiError } from '../../api/problem';

vi.mock('../../api/channelsApi');

const PUBLIC_CHANNEL = {
  id: 'chan-1',
  name: 'engineering',
  is_private: false as const,
  member_count: 4,
};

function renderAt(path = '/channels') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/channels" element={<ChannelsPage />} />
        <Route path="/channels/:channelId" element={<div>Channel view page</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ChannelsPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('shows an empty state when there are no public channels to join', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    renderAt();

    expect(await screen.findByText('No public channels to join right now.')).toBeInTheDocument();
  });

  it('lists public channels with member counts and pagination summary', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({
      items: [PUBLIC_CHANNEL],
      total: 1,
      limit: 50,
      offset: 0,
    });

    renderAt();

    expect(await screen.findByText('engineering')).toBeInTheDocument();
    expect(screen.getByText('4 members')).toBeInTheDocument();
    expect(screen.getByText('Showing 1-1 of 1')).toBeInTheDocument();
  });

  it('creates a channel and navigates to its channel view', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(channelsApi.createChannel).mockResolvedValue({
      id: 'chan-new',
      name: 'random',
      is_private: false,
      created_by: 'user-1',
      created_at: '2026-07-08T00:00:00.000Z',
      member_count: 1,
    });

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('No public channels to join right now.');
    await user.type(screen.getByLabelText(/name/i), 'random');
    await user.click(screen.getByRole('button', { name: /create channel/i }));

    await waitFor(() => {
      expect(channelsApi.createChannel).toHaveBeenCalledWith({ name: 'random', is_private: false });
    });
    expect(await screen.findByText('Channel view page')).toBeInTheDocument();
  });

  it('rejects an invalid channel name client-side without calling the API', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('No public channels to join right now.');
    await user.type(screen.getByLabelText(/name/i), 'bad/name!');
    await user.click(screen.getByRole('button', { name: /create channel/i }));

    expect(
      await screen.findByText('Use 1-80 letters, numbers, spaces, hyphens, or underscores.'),
    ).toBeInTheDocument();
    expect(channelsApi.createChannel).not.toHaveBeenCalled();
  });

  it('surfaces the name-taken 409 with the exact spec copy', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    vi.mocked(channelsApi.createChannel).mockRejectedValue(
      new ApiError({
        type: 'https://chatspace.example/problems/conflict',
        title: 'Conflict',
        status: 409,
        detail: 'A channel with this name already exists.',
        instance: '/v1/channels',
        correlation_id: '01J000EXAMPLE',
      }),
    );

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('No public channels to join right now.');
    await user.type(screen.getByLabelText(/name/i), 'engineering');
    await user.click(screen.getByRole('button', { name: /create channel/i }));

    expect(await screen.findByText('A channel with this name already exists.')).toBeInTheDocument();
  });

  it('joins a public channel and navigates to its channel view', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValue({
      items: [PUBLIC_CHANNEL],
      total: 1,
      limit: 50,
      offset: 0,
    });
    vi.mocked(channelsApi.joinChannel).mockResolvedValue({
      channel_id: PUBLIC_CHANNEL.id,
      user_id: 'user-1',
      role: 'member',
      joined_at: '2026-07-08T00:00:00.000Z',
    });

    const user = userEvent.setup();
    renderAt();

    await user.click(await screen.findByRole('button', { name: /^join$/i }));

    await waitFor(() => {
      expect(channelsApi.joinChannel).toHaveBeenCalledWith(PUBLIC_CHANNEL.id);
    });
    expect(await screen.findByText('Channel view page')).toBeInTheDocument();
  });

  it('paginates with Previous/Next using the offset envelope', async () => {
    vi.mocked(channelsApi.listPublicChannels).mockResolvedValueOnce({
      items: [PUBLIC_CHANNEL],
      total: 60,
      limit: 50,
      offset: 0,
    });

    const user = userEvent.setup();
    renderAt();

    await screen.findByText('Showing 1-50 of 60');
    const previousButton = screen.getByRole('button', { name: /previous/i });
    expect(previousButton).toBeDisabled();

    vi.mocked(channelsApi.listPublicChannels).mockResolvedValueOnce({
      items: [],
      total: 60,
      limit: 50,
      offset: 50,
    });

    await user.click(screen.getByRole('button', { name: /^next$/i }));

    await waitFor(() => {
      expect(channelsApi.listPublicChannels).toHaveBeenCalledWith({ limit: 50, offset: 50 });
    });
  });
});
