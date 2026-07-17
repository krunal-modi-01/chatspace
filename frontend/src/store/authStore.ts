import { create } from 'zustand';
import type { CurrentUser } from '../api/types';
import { useMyChannelsStore } from './myChannelsStore';
import { tokenStorage } from './tokenStorage';

export interface AuthSession {
  accessToken: string;
  refreshToken: string;
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: CurrentUser | null;
  /** True until the initial `GET /v1/me` bootstrap attempt has settled. */
  isBootstrapping: boolean;
  setSession: (session: AuthSession) => void;
  setUser: (user: CurrentUser | null) => void;
  setBootstrapped: () => void;
  clearSession: () => void;
}

const persisted = tokenStorage.load();

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: persisted?.accessToken ?? null,
  refreshToken: persisted?.refreshToken ?? null,
  user: null,
  isBootstrapping: persisted !== null,

  setSession: (session) => {
    tokenStorage.save(session);
    set({ accessToken: session.accessToken, refreshToken: session.refreshToken });
  },

  setUser: (user) => set({ user }),

  setBootstrapped: () => set({ isBootstrapping: false }),

  clearSession: () => {
    tokenStorage.clear();
    set({ accessToken: null, refreshToken: null, user: null, isBootstrapping: false });
    // `myChannelsStore` (T51) is a shared, module-scoped store that outlives
    // component mount/unmount — it must be wiped on every session teardown
    // (explicit logout, forced logout via WS `revoked`/`deactivated`, or a
    // failed token refresh) so a subsequent login in the same tab (SPA
    // navigation, no page reload) never briefly renders the previous
    // account's private channel names/roles. `clearSession` is the single
    // choke point all of those paths already go through.
    useMyChannelsStore.getState().reset();
  },
}));

/** Non-hook accessor for use in modules outside React (e.g. the HTTP
 * client's 401->refresh interceptor), which cannot call hooks. */
export const authStoreApi = {
  getState: useAuthStore.getState,
  setState: useAuthStore.setState,
};
