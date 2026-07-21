import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Badge } from './Badge';

describe('Badge', () => {
  it('defaults to the neutral tint recipe', () => {
    render(<Badge>member</Badge>);

    const badge = screen.getByText('member');
    expect(badge).toHaveClass('tint-neutral');
    expect(badge).not.toHaveClass('tint-surface');
    expect(badge.style.getPropertyValue('--tint')).toBe('');
  });

  it('mixes --color-accent for the accent variant', () => {
    render(<Badge variant="accent">admin</Badge>);

    const badge = screen.getByText('admin');
    expect(badge).toHaveClass('tint-surface');
    expect(badge.style.getPropertyValue('--tint')).toBe('var(--color-accent)');
  });

  it('mixes --color-success for the success variant', () => {
    render(<Badge variant="success">Active</Badge>);

    const badge = screen.getByText('Active');
    expect(badge).toHaveClass('tint-surface');
    expect(badge.style.getPropertyValue('--tint')).toBe('var(--color-success)');
  });

  it('mixes --color-warning for the warning variant', () => {
    render(<Badge variant="warning">pending</Badge>);

    const badge = screen.getByText('pending');
    expect(badge).toHaveClass('tint-surface');
    expect(badge.style.getPropertyValue('--tint')).toBe('var(--color-warning)');
  });

  it('mixes --color-danger for the danger variant', () => {
    render(<Badge variant="danger">revoked</Badge>);

    const badge = screen.getByText('revoked');
    expect(badge).toHaveClass('tint-surface');
    expect(badge.style.getPropertyValue('--tint')).toBe('var(--color-danger)');
  });

  it('renders as a plain, non-interactive label (no role/button semantics)', () => {
    const { container } = render(<Badge>member</Badge>);
    expect(container.querySelector('button')).not.toBeInTheDocument();
    expect(container.querySelector('span')).toBeInTheDocument();
  });

  it('does not bake a `capitalize` text-transform into its base classes', () => {
    // Regression test: Badge must not force-capitalize every word of its
    // label (e.g. "This device" on SessionsPage), since not every call site
    // is a lowercase single-word enum value. RTL/jsdom can't observe
    // rendered CSS text-transform, so this asserts the class list directly
    // — the only way this regression is actually observable in tests.
    render(<Badge variant="accent">This device</Badge>);

    const badge = screen.getByText('This device');
    expect(badge.className.split(' ')).not.toContain('capitalize');
  });

  it('falls back to neutral styling for an unrecognized variant value from an open enum', () => {
    // Simulates a call site passing through an unmapped enum value coming
    // from an open server-side set (api-contract.md Conventions) — the
    // Badge itself must not crash or silently drop styling even if a
    // caller's mapping function has a gap.
    render(<Badge variant={'unknown-variant' as unknown as never}>mystery</Badge>);

    const badge = screen.getByText('mystery');
    expect(badge).toHaveClass('tint-neutral');
  });
});
