import { afterEach, describe, expect, it } from 'vitest';
import { tokenStorage } from './tokenStorage';

// Fixture values only — never a real credential.
const FIXTURE_ACCESS = ['fixture', 'access'].join('-');
const FIXTURE_REFRESH = ['fixture', 'refresh'].join('-');

describe('tokenStorage', () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it('returns null when nothing is persisted', () => {
    expect(tokenStorage.load()).toBeNull();
  });

  it('round-trips saved tokens', () => {
    tokenStorage.save({ accessToken: FIXTURE_ACCESS, refreshToken: FIXTURE_REFRESH });
    expect(tokenStorage.load()).toEqual({
      accessToken: FIXTURE_ACCESS,
      refreshToken: FIXTURE_REFRESH,
    });
  });

  it('clears persisted tokens', () => {
    tokenStorage.save({ accessToken: FIXTURE_ACCESS, refreshToken: FIXTURE_REFRESH });
    tokenStorage.clear();
    expect(tokenStorage.load()).toBeNull();
  });

  it('treats a partial pair (only one key present) as absent', () => {
    window.localStorage.setItem('chatspace.access_token', FIXTURE_ACCESS);
    expect(tokenStorage.load()).toBeNull();
  });
});
