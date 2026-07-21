import { describe, expect, it } from 'vitest';
import { channelRoleBadgeVariant } from './channelRoleBadgeVariant';

describe('channelRoleBadgeVariant', () => {
  it('maps admin to accent', () => {
    expect(channelRoleBadgeVariant('admin')).toBe('accent');
  });

  it('maps member to neutral', () => {
    expect(channelRoleBadgeVariant('member')).toBe('neutral');
  });

  it('falls back to neutral for an unrecognized value from the open server-side enum', () => {
    expect(channelRoleBadgeVariant('owner')).toBe('neutral');
  });
});
