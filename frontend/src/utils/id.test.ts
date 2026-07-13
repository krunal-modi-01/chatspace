import { afterEach, describe, expect, it, vi } from 'vitest';
import { generateClientId } from './id';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe('generateClientId', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns crypto.randomUUID()’s value when available', () => {
    const uuid = '11111111-2222-4333-8444-555555555555';
    vi.stubGlobal('crypto', { randomUUID: () => uuid });

    expect(generateClientId()).toBe(uuid);
  });

  it('falls back to a UUIDv4-shaped value when crypto.randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {});

    const id = generateClientId();

    // Must be UUID-shaped: the backend strictly parses `Idempotency-Key` as a
    // UUID and rejects anything else with a 400 (see utils/id.ts doc comment).
    expect(id).toMatch(UUID_RE);
  });

  it('produces distinct fallback ids across calls', () => {
    vi.stubGlobal('crypto', {});

    const first = generateClientId();
    const second = generateClientId();

    expect(first).not.toBe(second);
  });
});
