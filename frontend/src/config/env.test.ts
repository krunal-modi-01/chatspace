import { afterEach, describe, expect, it, vi } from 'vitest';
import { deriveWsBaseUrl, readWsBaseUrl } from './env';

describe('deriveWsBaseUrl', () => {
  it('swaps http -> ws for an absolute http API base', () => {
    expect(deriveWsBaseUrl('http://localhost:8000/v1')).toBe('ws://localhost:8000/v1/ws');
  });

  it('swaps https -> wss for an absolute https API base', () => {
    expect(deriveWsBaseUrl('https://api.chatspace.example/v1')).toBe('wss://api.chatspace.example/v1/ws');
  });

  it('resolves a relative base against window.location, using wss on an https page', () => {
    const originalLocation = window.location;
    // jsdom's `window.location` setter rejects partial assignment; replace
    // the whole property instead of mutating individual fields.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, protocol: 'https:', host: 'app.chatspace.example' },
    });

    try {
      expect(deriveWsBaseUrl('/v1')).toBe('wss://app.chatspace.example/v1/ws');
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
    }
  });

  it('resolves a relative base against window.location, using ws on a plain http page', () => {
    const originalLocation = window.location;
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, protocol: 'http:', host: 'localhost:5173' },
    });

    try {
      expect(deriveWsBaseUrl('/v1')).toBe('ws://localhost:5173/v1/ws');
    } finally {
      Object.defineProperty(window, 'location', { configurable: true, value: originalLocation });
    }
  });
});

describe('readWsBaseUrl', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('falls back to deriveWsBaseUrl when no override is set', () => {
    vi.stubEnv('VITE_WS_BASE_URL', '');
    expect(readWsBaseUrl('http://localhost:8000/v1')).toBe('ws://localhost:8000/v1/ws');
  });

  it('uses an explicit override verbatim, trimming a trailing slash', () => {
    vi.stubEnv('VITE_WS_BASE_URL', 'wss://override.example/v1/ws/');
    expect(readWsBaseUrl('http://localhost:8000/v1')).toBe('wss://override.example/v1/ws');
  });

  it('uses an explicit override with no trailing slash unchanged', () => {
    vi.stubEnv('VITE_WS_BASE_URL', 'wss://override.example/v1/ws');
    expect(readWsBaseUrl('http://localhost:8000/v1')).toBe('wss://override.example/v1/ws');
  });
});
