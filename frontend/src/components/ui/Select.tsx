import { forwardRef, type SelectHTMLAttributes } from 'react';

export type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

const BASE_CLASSES =
  'mt-1 block w-full rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 ' +
  'text-sm text-[var(--color-text-primary)] transition-colors duration-150 ease-out focus:outline-none ' +
  'focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-0 ' +
  'disabled:cursor-not-allowed disabled:bg-[var(--color-surface-raised)] disabled:text-[var(--color-text-tertiary)]';

/** Shared select primitive, styled to match `Input` per
 * architecture/design-tokens.md §6 (no dedicated select token existed —
 * mirrors the input's border/focus/disabled treatment). */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, children, ...rest },
  ref,
) {
  return (
    <select ref={ref} className={[BASE_CLASSES, className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </select>
  );
});
