import type { CSSProperties, JSX, ReactNode } from 'react';

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

/** Custom-property carrier for the `.tint-surface` recipe (index.css,
 * architecture/design-tokens.md §12) — React's `CSSProperties` doesn't
 * declare arbitrary custom properties, so this narrow extension is needed to
 * set `--tint` from a variant prop instead of a raw palette class. */
type TintStyle = CSSProperties & { '--tint'?: string };

/** Maps each variant to the semantic color token the `.tint-surface` recipe
 * mixes into background/border (architecture/design-tokens.md §12) — never
 * a raw `amber-*`, `emerald-*`, `red-*` Tailwind palette class. `info` has no
 * tint (flat neutral surface, `.tint-neutral`); the other three set `--tint`
 * and use `.tint-surface`. */
const VARIANT_TINT: Record<AlertVariant, string | null> = {
  info: null,
  warning: 'var(--color-warning)',
  error: 'var(--color-danger)',
  success: 'var(--color-success)',
};

const VARIANT_CLASSES: Record<AlertVariant, string> = {
  info: 'tint-neutral',
  warning: 'tint-surface',
  error: 'tint-surface',
  success: 'tint-surface',
};

const DEFAULT_ROLE: Record<AlertVariant, 'alert' | 'status'> = {
  info: 'status',
  warning: 'alert',
  error: 'alert',
  success: 'status',
};

/** Shared status/error surface per architecture/design-tokens.md §6/§12 —
 * replaces ad hoc `role="alert"`/`role="status"` divs scattered across pages,
 * and (T53–T56) the banner's own hand-rolled `amber-*`, `emerald-*`, `red-*`
 * palette classes with the token-driven badge-tint recipe. */
export function AlertBanner({ variant, title, role, children }: AlertBannerProps): JSX.Element {
  const tint = VARIANT_TINT[variant];
  // `info` has no `--tint` (flat `.tint-neutral` surface). That shared
  // recipe (architecture/design-tokens.md §12) defaults text to
  // `--color-text-secondary` for Badge/T58's dimmer pill use case — applied
  // as-is here it would silently dim AlertBanner's `info` variant from its
  // original full-emphasis `--color-text-primary` (code review finding,
  // T53-T56), contradicting this ticket's "no intended visual change beyond
  // typography" invariant. Pinned back to the original color via an inline
  // override (wins over the `.tint-neutral` class regardless of Tailwind's
  // generated-utility ordering) pending an explicit design decision on
  // whether `info` should adopt the dimmer neutral tone.
  const style: TintStyle | undefined =
    tint !== null ? { '--tint': tint } : { color: 'var(--color-text-primary)' };

  return (
    <div
      role={role ?? DEFAULT_ROLE[variant]}
      style={style}
      className={`rounded-md border px-4 py-3 text-body ${VARIANT_CLASSES[variant]}`}
    >
      {title !== undefined && <p className="font-medium">{title}</p>}
      {children}
    </div>
  );
}
