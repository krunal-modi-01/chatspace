import { describe, expect, it } from 'vitest';
import { inferMediaKind, preflightSizeError, preflightTypeError } from './mediaValidation';

function makeFile(name: string, type: string, size: number): File {
  return new File([new Uint8Array(size)], name, { type });
}

describe('inferMediaKind', () => {
  it('infers image for the allowlisted image MIME types', () => {
    expect(inferMediaKind('image/png')).toBe('image');
    expect(inferMediaKind('image/jpeg')).toBe('image');
    expect(inferMediaKind('image/gif')).toBe('image');
    expect(inferMediaKind('image/webp')).toBe('image');
  });

  it('infers video for the allowlisted video MIME types', () => {
    expect(inferMediaKind('video/mp4')).toBe('video');
    expect(inferMediaKind('video/webm')).toBe('video');
  });

  it('falls back to file for everything else, including excluded SVG', () => {
    expect(inferMediaKind('image/svg+xml')).toBe('file');
    expect(inferMediaKind('application/pdf')).toBe('file');
    expect(inferMediaKind('')).toBe('file');
  });
});

describe('preflightSizeError', () => {
  it('rejects an image over the 10 MB cap', () => {
    const file = makeFile('big.png', 'image/png', 11 * 1024 * 1024);
    expect(preflightSizeError(file, 'image')).toMatch(/too large/i);
  });

  it('accepts an image at or under the 10 MB cap', () => {
    const file = makeFile('ok.png', 'image/png', 10 * 1024 * 1024);
    expect(preflightSizeError(file, 'image')).toBeNull();
  });

  it('rejects a file over the 50 MB cap and a video over the 200 MB cap', () => {
    expect(preflightSizeError(makeFile('doc.pdf', 'application/pdf', 51 * 1024 * 1024), 'file')).toMatch(/too large/i);
    expect(preflightSizeError(makeFile('clip.mp4', 'video/mp4', 201 * 1024 * 1024), 'video')).toMatch(/too large/i);
  });
});

describe('preflightTypeError', () => {
  it('rejects a disallowed declared image content type', () => {
    const file = makeFile('bad.svg', 'image/svg+xml', 10);
    expect(preflightTypeError(file, 'image')).toMatch(/not a supported image type/i);
  });

  it('rejects a disallowed declared video content type', () => {
    const file = makeFile('clip.mov', 'video/quicktime', 10);
    expect(preflightTypeError(file, 'video')).toMatch(/not a supported video type/i);
  });

  it('has no fixed allowlist for kind=file', () => {
    const file = makeFile('doc.pdf', 'application/pdf', 10);
    expect(preflightTypeError(file, 'file')).toBeNull();
  });
});
