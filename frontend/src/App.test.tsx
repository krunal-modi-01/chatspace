import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { useAuthStore } from './store/authStore';

// Non-secret fixture — never a real credential.
const FIXTURE_ACCESS = ['fixture', 'access'].join('-');
const FIXTURE_REFRESH = ['fixture', 'refresh'].join('-');

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe('App route split', () => {
  afterEach(() => {
    useAuthStore.setState({
      accessToken: null,
      refreshToken: null,
      user: null,
      isBootstrapping: false,
    });
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('redirects an unauthenticated visitor from a protected route to /login', async () => {
    renderAt('/');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in to chatspace/i })).toBeInTheDocument();
    });
  });

  it('renders the public login route without requiring auth', () => {
    renderAt('/login');

    expect(screen.getByRole('heading', { name: /sign in to chatspace/i })).toBeInTheDocument();
  });

  it('renders the protected app shell for an authenticated user', async () => {
    vi.stubGlobal('fetch', vi.fn());
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS,
      refreshToken: FIXTURE_REFRESH,
      user: {
        id: 'user-1',
        username: 'alice',
        email: 'alice@co.com',
        first_name: 'Alice',
        last_name: 'Doe',
        avatar_url: null,
        role: 'user',
        is_active: true,
        last_seen: null,
        created_at: '2026-07-02T14:31:07.482Z',
      },
      isBootstrapping: false,
    });

    renderAt('/');

    expect(await screen.findByRole('heading', { name: /welcome, alice/i })).toBeInTheDocument();

    // "Sign out" lives behind the account menu now (consolidated nav).
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /alice/i }));
    expect(screen.getByRole('menuitem', { name: /sign out/i })).toBeInTheDocument();
  });

  it('redirects an authenticated user away from /login', async () => {
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS,
      refreshToken: FIXTURE_REFRESH,
      user: null,
      isBootstrapping: false,
    });
    vi.stubGlobal('fetch', vi.fn());

    renderAt('/login');

    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: /sign in to chatspace/i })).not.toBeInTheDocument();
    });
  });
});
