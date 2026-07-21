import type { CSSProperties, JSX, ReactNode } from 'react';

export type BadgeVariant = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export interface BadgeProps {
  /** Semantic tint — see architecture/design-tokens.md §12 and
   * docs/design/DESIGN_SYSTEM.md §3.2. Defaults to `neutral`. */
  variant?: BadgeVariant;
  children: ReactNode;
  /** Badge renders `children` verbatim — it does not apply a CSS
   * `text-transform`, since not every label is a lowercase single-word enum
   * value (e.g. "This device" on `SessionsPage`). Callers whose label *is* a
   * lowercase enum value (channel role, invite status, etc.) should opt in
   * with `className="capitalize"`. */
  className?: string;
}

/** Custom-property carrier for the `.tint-surface` recipe (index.css,
 * architecture/design-tokens.md §12) — mirrors `AlertBanner`'s `TintStyle`,
 * since React's `CSSProperties` doesn't declare arbitrary custom
 * properties. */
type TintStyle = CSSProperties & { '--tint'?: string };

/** Maps each variant to the semantic color token the `.tint-surface` recipe
 * mixes into background/text (architecture/design-tokens.md §12) — never a
 * raw `amber-*`/`emerald-*`/`red-*`/`gray-*` Tailwind palette class.
 * `neutral` has no tint to mix and uses the flat `.tint-neutral` utility
 * instead. */
const VARIANT_TINT: Record<BadgeVariant, string | null> = {
  neutral: null,
  accent: 'var(--color-accent)',
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
  danger: 'var(--color-danger)',
};

/**
 * The single badge/pill primitive (T58, docs/design/DESIGN_SYSTEM.md §3.2) —
 * replaces the six hand-rolled implementations the v3 UX review found
 * (`RoleBadge` defined twice, `VisibilityBadge`, invites' `StatusBadge`, the
 * active/inactive pill, and the "This device" pill), all of which hardcoded
 * raw Tailwind palette classes instead of the token-driven tint recipe.
 *
 * A plain label, never interactive — callers own the enum→variant mapping
 * for their own domain (channel role, invite status, etc.) since those
 * vocabularies are open sets server-side (api-contract.md Conventions):
 * an unmapped/unknown value must still render safely, so every call site's
 * mapping function is expected to fall back to `neutral` rather than throw
 * or omit styling.
 */
export function Badge({ variant = 'neutral', children, className }: BadgeProps): JSX.Element {
  // `?? null` guards against a variant value that isn't one of the four
  // known keys (e.g. a caller's mapping function forwarding an unrecognized
  // enum value from an open server-side set unchanged) — falls back to the
  // flat neutral recipe rather than setting `--tint` to `undefined`.
  const tint = VARIANT_TINT[variant] ?? null;
  const style: TintStyle | undefined = tint !== null ? { '--tint': tint } : undefined;
  const classes = [
    'inline-flex w-fit items-center rounded-full px-2 py-0.5 text-caption font-semibold',
    tint !== null ? 'tint-surface' : 'tint-neutral',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes} style={style}>
      {children}
    </span>
  );
}
