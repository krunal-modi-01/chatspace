import type { HTMLAttributes, JSX } from 'react';

export type CardProps = HTMLAttributes<HTMLDivElement>;

/** Bordered/padded surface primitive per architecture/design-tokens.md §6,
 * used for auth form panels and other content panels. */
export function Card({ className, children, ...rest }: CardProps): JSX.Element {
  const classes = [
    'w-full rounded-lg bg-[var(--color-surface-overlay)] p-6 shadow-sm',
    'dark:border dark:border-[var(--color-border)] dark:shadow-none',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}
