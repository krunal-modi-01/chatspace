import type { ComponentPropsWithRef, ElementType, JSX, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'link';
export type ButtonSize = 'sm' | 'md';

type ButtonOwnProps = {
  /** Visual style — architecture/design-tokens.md §2/§12,
   * docs/design/DESIGN_SYSTEM.md §3.1. Defaults to `primary`.
   * `ghost` — no border/fill, hover surface; for low-emphasis/table
   * actions. `link` — text + accent, no box; for inline
   * navigation-as-action (also usable via `as={Link}`, see below). */
  variant?: ButtonVariant;
  /** `md` (default, `--control-height-md`) for forms/page actions; `sm`
   * (`--control-height-sm`) for controls inside table rows and dense
   * toolbars (architecture/design-tokens.md §6). */
  size?: ButtonSize;
  /** Width is intrinsic (content-sized) by default; full width is opt-in.
   * Auth forms use `fullWidth`; everything else does not
   * (docs/design/DESIGN_SYSTEM.md §3.1). */
  fullWidth?: boolean;
  /** When true, disables the control and swaps its label for `loadingText`
   * (or a spinner if no loading text is given) — never a silent no-op. */
  isLoading?: boolean;
  /** Label shown while `isLoading` is true. Falls back to a spinner + children. */
  loadingText?: string;
  disabled?: boolean;
  className?: string;
  children?: ReactNode;
};

/**
 * Polymorphic `as` — e.g. `<Button as={Link} to="/channels">` — renders the
 * button's variant/size/state classes onto react-router's `Link` (or a
 * plain `a`) instead of copy-pasting the class string onto the anchor by
 * hand (docs/design/DESIGN_SYSTEM.md §3.1 — the Dashboard's "Browse
 * channels" CTA was exactly this defect). Defaults to a native `<button>`.
 */
export type ButtonProps<E extends ElementType = 'button'> = ButtonOwnProps & {
  as?: E;
} & Omit<ComponentPropsWithRef<E>, keyof ButtonOwnProps | 'as'>;

const BASE_CLASSES =
  'inline-flex items-center justify-center rounded-md transition-colors duration-150 ease-out ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] ' +
  'focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--color-surface)] ' +
  'disabled:cursor-not-allowed disabled:opacity-50 ' +
  'aria-disabled:cursor-not-allowed aria-disabled:opacity-50';

/** Press feedback (architecture/design-tokens.md §11) — omitted for `link`,
 * which reads as inline text rather than a discrete control surface. */
const PRESS_CLASSES = 'active:scale-[0.98] disabled:active:scale-100 aria-disabled:active:scale-100';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: `font-semibold bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] ${PRESS_CLASSES}`,
  secondary:
    `font-semibold border border-[var(--color-border)] bg-[var(--color-surface)] ` +
    `text-[var(--color-text-primary)] hover:bg-[var(--color-surface-raised)] ${PRESS_CLASSES}`,
  danger: `font-semibold bg-[var(--color-danger)] text-white hover:opacity-90 ${PRESS_CLASSES}`,
  ghost:
    `font-semibold bg-transparent text-[var(--color-text-primary)] ` +
    `hover:bg-[var(--color-surface-raised)] ${PRESS_CLASSES}`,
  link: 'font-medium bg-transparent text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]',
};

/** Boxed sizing (height/padding) for every variant except `link`, which
 * stays text-sized (no fixed control height/padding) — density scale,
 * architecture/design-tokens.md §6. */
const BOX_SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'h-[var(--control-height-sm)] px-2.5 gap-1.5 text-caption',
  md: 'h-[var(--control-height-md)] px-3 gap-2 text-sm',
};

const LINK_SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'gap-1 text-caption',
  md: 'gap-1.5 text-sm',
};

const SPINNER_SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: 'h-3.5 w-3.5',
  md: 'h-4 w-4',
};

function Spinner({ size }: { size: ButtonSize }): JSX.Element {
  return (
    <svg
      className={`${SPINNER_SIZE_CLASSES[size]} animate-spin`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

/**
 * Shared button primitive — docs/design/DESIGN_SYSTEM.md §3.1,
 * architecture/design-tokens.md §13/§14. Covers the `default`/`hover`/
 * `focus-visible`/`disabled`/`loading` states required for every
 * interactive primitive. Width is intrinsic (content-sized) by default;
 * opt in to full width via `fullWidth` (auth forms only).
 */
export function Button<E extends ElementType = 'button'>({
  as,
  variant = 'primary',
  size = 'md',
  fullWidth = false,
  isLoading = false,
  loadingText,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps<E>): JSX.Element {
  const Component = (as ?? 'button') as ElementType;
  const isNativeButton = Component === 'button';
  const isDisabled = Boolean(disabled) || isLoading;
  const sizeClasses = variant === 'link' ? LINK_SIZE_CLASSES[size] : BOX_SIZE_CLASSES[size];

  const classes = [
    BASE_CLASSES,
    VARIANT_CLASSES[variant],
    sizeClasses,
    fullWidth ? 'w-full' : 'w-fit',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  // Non-button elements (an `<a>`, react-router's `Link`) have no native
  // `disabled` semantics — fall back to `aria-disabled` + removing it from
  // the tab order, and swallow the caller's `onClick` while disabled, so a
  // link-rendered Button never silently still navigates when "disabled".
  const stateProps: Record<string, unknown> = { 'aria-busy': isLoading || undefined };
  if (isNativeButton) {
    stateProps.disabled = isDisabled;
  } else if (isDisabled) {
    stateProps['aria-disabled'] = true;
    stateProps.tabIndex = -1;
    stateProps.onClick = (event: { preventDefault: () => void }) => event.preventDefault();
  }

  return (
    <Component className={classes} {...rest} {...stateProps}>
      {isLoading && <Spinner size={size} />}
      {isLoading ? (loadingText ?? children) : children}
    </Component>
  );
}
