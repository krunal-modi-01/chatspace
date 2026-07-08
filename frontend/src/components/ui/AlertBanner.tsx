import type { JSX, ReactNode } from 'react';

export type AlertVariant = 'info' | 'warning' | 'error' | 'success';

export interface AlertBannerProps {
  variant: AlertVariant;
  /** Bold lead-in line, e.g. a problem+json `title`. Optional — some banners
   * (uniform reset-request confirmation, etc.) are single-line. */
  title?: string;
  /** ARIA role. Defaults per variant: `alert` for `error`/`warning` (must
   * interrupt), `status` for `success`/`info` (polite). Override when a
   * caller needs a specific role regardless of variant. */
  role?: 'alert' | 'status';
  children?: ReactNode;
}

const VARIANT_CLASSES: Record<AlertVariant, string> = {
  info: 'border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-primary)]',
  warning: 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-800/60 dark:bg-amber-950/40 dark:text-amber-300',
  error: 'border-red-300 bg-red-50 text-red-800 dark:border-red-800/60 dark:bg-red-950/40 dark:text-red-300',
  success:
    'border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-800/60 dark:bg-emerald-950/40 dark:text-emerald-300',
};

const DEFAULT_ROLE: Record<AlertVariant, 'alert' | 'status'> = {
  info: 'status',
  warning: 'alert',
  error: 'alert',
  success: 'status',
};

/** Shared status/error surface per architecture/design-tokens.md §6 — replaces
 * ad hoc `role="alert"`/`role="status"` divs scattered across pages. */
export function AlertBanner({ variant, title, role, children }: AlertBannerProps): JSX.Element {
  return (
    <div
      role={role ?? DEFAULT_ROLE[variant]}
      className={`rounded-md border px-4 py-3 text-body ${VARIANT_CLASSES[variant]}`}
    >
      {title !== undefined && <p className="font-medium">{title}</p>}
      {children}
    </div>
  );
}
