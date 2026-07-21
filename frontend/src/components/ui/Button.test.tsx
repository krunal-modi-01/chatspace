import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef, type MouseEvent } from 'react';
import { Link, MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';

describe('Button', () => {
  it('defaults to intrinsic (content-sized) width, not full width', () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveClass('w-fit');
    expect(button).not.toHaveClass('w-full');
  });

  it('opts into full width via `fullWidth`', () => {
    render(<Button fullWidth>Sign in</Button>);
    const button = screen.getByRole('button', { name: 'Sign in' });
    expect(button).toHaveClass('w-full');
    expect(button).not.toHaveClass('w-fit');
  });

  it('defaults to the `primary` variant and `md` size', () => {
    render(<Button>Default</Button>);
    const button = screen.getByRole('button', { name: 'Default' });
    expect(button).toHaveClass('bg-[var(--color-accent)]');
    expect(button).toHaveClass('h-[var(--control-height-md)]');
  });

  it('renders every variant with its documented treatment', () => {
    const { rerender } = render(<Button variant="secondary">Cancel</Button>);
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveClass('border');

    rerender(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass('bg-[var(--color-danger)]');

    rerender(<Button variant="ghost">Dismiss</Button>);
    const ghost = screen.getByRole('button', { name: 'Dismiss' });
    expect(ghost).toHaveClass('bg-transparent');
    expect(ghost).not.toHaveClass('border');

    rerender(<Button variant="link">Learn more</Button>);
    const link = screen.getByRole('button', { name: 'Learn more' });
    expect(link).toHaveClass('text-[var(--color-accent)]');
    expect(link).not.toHaveClass('h-[var(--control-height-md)]');
  });

  it('sizes `sm` to the compact control-height token for table/row actions', () => {
    render(<Button size="sm">Revoke</Button>);
    expect(screen.getByRole('button', { name: 'Revoke' })).toHaveClass('h-[var(--control-height-sm)]');
  });

  it('shows a spinner and swaps the label to `loadingText` while loading — never a silent no-op', () => {
    render(
      <Button isLoading loadingText="Saving…">
        Save
      </Button>,
    );
    const button = screen.getByRole('button', { name: /saving/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button.querySelector('svg')).toBeInTheDocument();
    expect(screen.queryByText('Save')).not.toBeInTheDocument();
  });

  it('falls back to a spinner + the original children when loading without `loadingText`', () => {
    render(<Button isLoading>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button.querySelector('svg')).toBeInTheDocument();
  });

  it('disables the control and applies the disabled treatment', () => {
    render(<Button disabled>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toBeDisabled();
    expect(button).toHaveClass('disabled:opacity-50');
  });

  it('never fires onClick while disabled or loading', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Save
      </Button>,
    );
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('shows a visible focus-visible ring recipe (design-tokens §12)', () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveClass('focus-visible:ring-2');
    expect(button).toHaveClass('focus-visible:ring-offset-2');
  });

  it('forwards a ref to the underlying DOM button (row-action focus management)', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Save</Button>);
    expect(ref.current).toBeInstanceOf(HTMLButtonElement);
  });

  it('merges a caller-supplied className without dropping the base classes', () => {
    render(<Button className="my-custom-class">Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveClass('my-custom-class');
    expect(button).toHaveClass('bg-[var(--color-accent)]');
  });

  describe('link rendering (`as`)', () => {
    it('renders as react-router `Link` while keeping the Button visual treatment', () => {
      render(
        <MemoryRouter>
          <Button as={Link} to="/channels" variant="primary">
            Browse channels
          </Button>
        </MemoryRouter>,
      );
      const link = screen.getByRole('link', { name: 'Browse channels' });
      expect(link.tagName).toBe('A');
      expect(link).toHaveAttribute('href', '/channels');
      expect(link).toHaveClass('bg-[var(--color-accent)]');
    });

    it('renders as a plain anchor via `as="a"`', () => {
      render(
        <Button as="a" href="https://example.com" variant="link">
          External
        </Button>,
      );
      const link = screen.getByRole('link', { name: 'External' });
      expect(link.tagName).toBe('A');
      expect(link).toHaveAttribute('href', 'https://example.com');
    });

    it('marks a disabled link-rendered Button as aria-disabled and blocks navigation', async () => {
      const user = userEvent.setup();
      const onClick = vi.fn((event: MouseEvent) => event.preventDefault());
      render(
        <MemoryRouter>
          <Button as={Link} to="/channels" disabled onClick={onClick}>
            Browse channels
          </Button>
        </MemoryRouter>,
      );
      const link = screen.getByRole('link', { name: 'Browse channels' });
      expect(link).toHaveAttribute('aria-disabled', 'true');
      expect(link).toHaveAttribute('tabIndex', '-1');
      await user.click(link);
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
