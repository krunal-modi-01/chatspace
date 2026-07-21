import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AlertBanner } from './AlertBanner';

describe('AlertBanner', () => {
  it('defaults to role="status" and the neutral recipe for info', () => {
    render(<AlertBanner variant="info">Heads up</AlertBanner>);

    const banner = screen.getByRole('status');
    expect(banner).toHaveClass('tint-neutral');
    expect(banner).not.toHaveClass('tint-surface');
    expect(banner.style.getPropertyValue('--tint')).toBe('');
    // Pinned to the original full-emphasis text color rather than the
    // `.tint-neutral` recipe's dimmer `--color-text-secondary` default —
    // see the inline comment in AlertBanner.tsx (code review finding,
    // T53-T56: preserves "no visual change beyond typography").
    expect(banner.style.color).toBe('var(--color-text-primary)');
  });

  it('defaults to role="alert" and mixes --color-danger for error', () => {
    render(
      <AlertBanner variant="error" title="Validation failed">
        content must not be empty
      </AlertBanner>,
    );

    const banner = screen.getByRole('alert');
    expect(banner).toHaveClass('tint-surface');
    expect(banner.style.getPropertyValue('--tint')).toBe('var(--color-danger)');
    expect(screen.getByText('Validation failed')).toBeInTheDocument();
    expect(screen.getByText('content must not be empty')).toBeInTheDocument();
  });

  it('defaults to role="alert" and mixes --color-warning for warning', () => {
    render(<AlertBanner variant="warning">careful</AlertBanner>);

    const banner = screen.getByRole('alert');
    expect(banner).toHaveClass('tint-surface');
    expect(banner.style.getPropertyValue('--tint')).toBe('var(--color-warning)');
  });

  it('defaults to role="status" and mixes --color-success for success', () => {
    render(<AlertBanner variant="success">saved</AlertBanner>);

    const banner = screen.getByRole('status');
    expect(banner).toHaveClass('tint-surface');
    expect(banner.style.getPropertyValue('--tint')).toBe('var(--color-success)');
  });

  it('lets a caller override the default role', () => {
    render(
      <AlertBanner variant="success" role="alert">
        saved
      </AlertBanner>,
    );

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('omits the title paragraph when no title is given', () => {
    const { container } = render(<AlertBanner variant="info">just text</AlertBanner>);
    expect(container.querySelector('p.font-medium')).not.toBeInTheDocument();
  });
});
