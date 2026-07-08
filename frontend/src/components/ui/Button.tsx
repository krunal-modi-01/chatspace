import type { ButtonHTMLAttributes, JSX } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style — see architecture/design-tokens.md §6. Defaults to `primary`. */
  variant?: ButtonVariant;
  /** When true, disables the button and swaps its label for `loadingText` (or a
   * spinner if no loading text is provided) — never a silent no-op. */
  isLoading?: boolean;
  /** Label shown while `isLoading` is true. Falls back to a spinner + children. */
  loadingText?: string;
}

const BASE_CLASSES =
  'inline-flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold ' +
  'transition-colors duration-150 ease-out active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 ' +
  'focus-visible:ring-[var(--color-accent)] focus-visible:ring-offset-2 ' +
  'focus-visible:ring-offset-[var(--color-surface)] disabled:cursor-not-allowed disabled:opacity-50 ' +
  'disabled:active:scale-100';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)]',
  secondary:
    'border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] ' +
    'hover:bg-[var(--color-surface-raised)]',
  danger: 'bg-[var(--color-danger)] text-white hover:opacity-90',
};

const SPINNER = (
  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
    />
  </svg>
);

/** Shared button primitive per architecture/design-tokens.md §6. Covers the
 * `default`/`hover`/`focus-visible`/`disabled`/`loading` states required for
 * every interactive primitive (§5). */
export function Button({
  variant = 'primary',
  isLoading = false,
  loadingText,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps): JSX.Element {
  const classes = [BASE_CLASSES, VARIANT_CLASSES[variant], className].filter(Boolean).join(' ');

  return (
    <button className={classes} disabled={disabled || isLoading} aria-busy={isLoading} {...rest}>
      {isLoading && SPINNER}
      {isLoading ? (loadingText ?? children) : children}
    </button>
  );
}
