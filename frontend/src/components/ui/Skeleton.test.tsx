import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Skeleton } from './Skeleton';

describe('Skeleton', () => {
  it('defaults to a decorative `line` shape hidden from assistive tech', () => {
    const { container } = render(<Skeleton />);
    const el = container.firstElementChild as HTMLElement;

    // Purely decorative per ACCESSIBILITY_GUIDELINES.md §4 — the caller,
    // not this primitive, owns the role="status"/aria-busy live region.
    expect(el).toHaveAttribute('aria-hidden', 'true');
    expect(el.tagName).toBe('SPAN');
    expect(el).toHaveAttribute('data-variant', 'line');
    expect(el.style.width).toBe('100%');
    expect(el.style.height).toBe('0.75rem');
    expect(el).toHaveClass('rounded-md');
  });

  it('shapes a `block` variant for avatar/thumbnail/media placeholders', () => {
    const { container } = render(<Skeleton variant="block" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el).toHaveAttribute('data-variant', 'block');
    expect(el.style.width).toBe('3rem');
    expect(el.style.height).toBe('3rem');
  });

  it('shapes a `row` variant sized to the nav-row density token by default', () => {
    const { container } = render(<Skeleton variant="row" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el).toHaveAttribute('data-variant', 'row');
    expect(el.style.width).toBe('100%');
    expect(el.style.height).toBe('var(--row-height-nav)');
  });

  it('lets a caller retarget a `row` skeleton to the table-row height token', () => {
    const { container } = render(<Skeleton variant="row" height="var(--row-height-table)" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el.style.height).toBe('var(--row-height-table)');
  });

  it('lets a caller override width/height explicitly for any variant', () => {
    const { container } = render(<Skeleton width="6rem" height="1.5rem" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el.style.width).toBe('6rem');
    expect(el.style.height).toBe('1.5rem');
  });

  it('supports a `full` radius for circular/pill shapes (e.g. an avatar-shaped block)', () => {
    const { container } = render(<Skeleton variant="block" rounded="full" width="2rem" height="2rem" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el).toHaveClass('rounded-full');
    expect(el).not.toHaveClass('rounded-md');
  });

  it('defaults to `rounded-md` (design-tokens.md §5) for line/block/row', () => {
    for (const variant of ['line', 'block', 'row'] as const) {
      const { container } = render(<Skeleton variant={variant} />);
      expect(container.firstElementChild).toHaveClass('rounded-md');
    }
  });

  it('applies the shimmer recipe class that is neutralized by prefers-reduced-motion in index.css', () => {
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild).toHaveClass('skeleton-shimmer');
  });

  it('merges a caller-supplied className without dropping the base classes', () => {
    const { container } = render(<Skeleton className="my-custom-class" />);
    const el = container.firstElementChild as HTMLElement;

    expect(el).toHaveClass('my-custom-class');
    expect(el).toHaveClass('skeleton-shimmer');
  });

  it('never crashes and always renders a hidden placeholder regardless of props combination', () => {
    const { container } = render(<Skeleton variant="row" rounded="full" width={0} height={0} />);
    expect(container.firstElementChild).toBeInTheDocument();
  });
});
