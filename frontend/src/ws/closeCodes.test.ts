import { describe, expect, it } from 'vitest';
import { classifyCloseCode, WsCloseCode } from './closeCodes';

describe('classifyCloseCode', () => {
  it('treats a client-initiated 1000 as terminal (no reconnect)', () => {
    expect(classifyCloseCode(WsCloseCode.NORMAL_CLOSURE, { clientInitiated: true })).toEqual({
      kind: 'stop',
      reason: 'client-initiated',
    });
  });

  it('treats a server-initiated 1000 as transient (reconnect)', () => {
    expect(classifyCloseCode(WsCloseCode.NORMAL_CLOSURE, { clientInitiated: false })).toEqual({
      kind: 'reconnect',
    });
  });

  it('4402 token-expired -> refresh and reconnect', () => {
    expect(classifyCloseCode(WsCloseCode.TOKEN_EXPIRED, { clientInitiated: false })).toEqual({
      kind: 'refresh-and-reconnect',
    });
  });

  it('4401 auth-failed -> refresh and reconnect (one retry before giving up)', () => {
    expect(classifyCloseCode(WsCloseCode.AUTH_FAILED, { clientInitiated: false })).toEqual({
      kind: 'refresh-and-reconnect',
    });
  });

  it('4403 token-revoked -> terminal stop', () => {
    expect(classifyCloseCode(WsCloseCode.TOKEN_REVOKED, { clientInitiated: false })).toEqual({
      kind: 'stop',
      reason: 'revoked',
    });
  });

  it('4404 user-deactivated -> terminal stop', () => {
    expect(classifyCloseCode(WsCloseCode.USER_DEACTIVATED, { clientInitiated: false })).toEqual({
      kind: 'stop',
      reason: 'deactivated',
    });
  });

  it.each([WsCloseCode.GOING_AWAY, WsCloseCode.HEARTBEAT_TIMEOUT, WsCloseCode.RATE_LIMITED])(
    '%i -> reconnect with backoff',
    (code) => {
      expect(classifyCloseCode(code, { clientInitiated: false })).toEqual({ kind: 'reconnect' });
    },
  );

  it('tolerates an undocumented/future close code as transient (open set)', () => {
    expect(classifyCloseCode(4999, { clientInitiated: false })).toEqual({ kind: 'reconnect' });
  });
});
