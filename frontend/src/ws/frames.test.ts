import { describe, expect, it } from 'vitest';
import type { ConversationTarget } from '../api/types';
import { buildTypingFrame, parseServerFrame } from './frames';

const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: '01J0CHANNEL0000000000000000' };

describe('buildTypingFrame', () => {
  it('builds the frozen { type: "typing", conversation } client frame', () => {
    expect(buildTypingFrame(CHANNEL)).toEqual({ type: 'typing', conversation: CHANNEL });
  });
});

describe('parseServerFrame — typing/presence tolerance (T34)', () => {
  it('parses a well-formed typing frame', () => {
    const raw = { type: 'typing', conversation: CHANNEL, data: { user_id: 'user-1', conversation: CHANNEL } };
    expect(parseServerFrame(raw)).toEqual(raw);
  });

  it('parses a well-formed presence frame', () => {
    const raw = { type: 'presence', conversation: null, data: { user_id: 'user-1', state: 'online', last_seen: null } };
    expect(parseServerFrame(raw)).toEqual(raw);
  });

  it('still tolerates an unrecognized type as an open enum', () => {
    expect(parseServerFrame({ type: 'something.else' })).toEqual({ type: 'something.else' });
  });
});
