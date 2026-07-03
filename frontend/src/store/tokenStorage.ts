/**
 * Storage abstraction for auth tokens.
 *
 * The API contract's Open Question #2 flags a possible future move of the
 * refresh token to an httpOnly cookie (a client-visible transport change).
 * Isolating storage behind this module means only this file needs to change
 * if/when that happens — nothing else in the app should reach into
 * localStorage directly for tokens.
 *
 * Tokens are opaque secrets: never log them (see CLAUDE.md security
 * requirements / redaction guard).
 */

const ACCESS_TOKEN_KEY = 'chatspace.access_token';
const REFRESH_TOKEN_KEY = 'chatspace.refresh_token';

export interface StoredTokens {
  accessToken: string;
  refreshToken: string;
}

export const tokenStorage = {
  load(): StoredTokens | null {
    const accessToken = window.localStorage.getItem(ACCESS_TOKEN_KEY);
    const refreshToken = window.localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!accessToken || !refreshToken) {
      return null;
    }
    return { accessToken, refreshToken };
  },

  save(tokens: StoredTokens): void {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
    window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
  },

  clear(): void {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};
