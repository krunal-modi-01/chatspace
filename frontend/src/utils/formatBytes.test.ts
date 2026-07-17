import { describe, expect, it } from 'vitest';
import { formatBytes } from './formatBytes';

describe('formatBytes', () => {
  it('formats sub-1KB sizes in bytes', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
  });

  it('formats KB/MB/GB with one decimal below 10, none at/above 10', () => {
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(formatBytes(10 * 1024)).toBe('10 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });

  it('never throws on negative/NaN input', () => {
    expect(formatBytes(Number.NaN)).toBe('0 B');
    expect(formatBytes(-5)).toBe('0 B');
  });
});
