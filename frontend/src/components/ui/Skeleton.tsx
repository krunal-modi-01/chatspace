import type { CSSProperties, JSX } from 'react';

export type SkeletonVariant = 'line' | 'block' | 'row';
export type SkeletonRounded = 'md' | 'full';

export interface SkeletonProps {
  /** Shape family (DESIGN_SYSTEM.md §3.6): `line` for a single text-line
   * placeholder (paragraph/label content), `block` for a rectangular region
   * (avatar/thumbnail/media/card), `row` for a full list/nav-row placeholder
   * sized to the row-height tokens (design-tokens.md §6). Defaults to `line`. */
  variant?: SkeletonVariant;
  /** CSS width override (e.g. `'60%'`, `'8rem'`, `120`). Defaults per variant. */
  width?: string | number;
  /** CSS height override (e.g. `'var(--row-height-table)'` for a table row
   * instead of the nav-row default). Defaults per variant. */
  height?: string | number;
  /** Corner radius family (design-tokens.md §5): `md` (default — matches
   * inputs/buttons/badges) or `full` (circular/pill shapes, e.g. an
   * avatar-shaped `block`). */
  rounded?: SkeletonRounded;
  className?: string;
}

const DEFAULT_WIDTH: Record<SkeletonVariant, string> = {
  line: '100%',
  block: '3rem',
  row: '100%',
};

const DEFAULT_HEIGHT: Record<SkeletonVariant, string> = {
  line: '0.75rem',
  block: '3rem',
  row: 'var(--row-height-nav)',
};

const ROUNDED_CLASSES: Record<SkeletonRounded, string> = {
  md: 'rounded-md',
  full: 'rounded-full',
};

/**
 * Shape-matching loading placeholder (DESIGN_SYSTEM.md §3.6) — renders the
 * *shape* of the eventual content (a line of text, an avatar/thumbnail
 * block, or a full list/nav row) so there is no layout jump when real data
 * arrives. Replaces bare "Loading…" text strings.
 *
 * Purely decorative (`aria-hidden="true"`): per
 * ACCESSIBILITY_GUIDELINES.md §4 ("`aria-busy`/hidden from SR as decorative
 * while a `status` announces loading"), the caller wraps the loading region
 * itself in a `role="status"`/`aria-busy="true"` container carrying the
 * accessible loading label (e.g. a visually-hidden "Loading channels…").
 * This primitive deliberately does not render that live region itself, so
 * a list of N stacked skeleton rows doesn't produce N redundant screen-
 * reader announcements.
 *
 * The shimmer is a CSS animation (`.skeleton-shimmer`, index.css) built on
 * `--motion-base` and is neutralized by the sitewide
 * `prefers-reduced-motion: reduce` override (index.css) per
 * design-tokens.md §11 — no separate reduced-motion branch is needed here.
 */
export function Skeleton({ variant = 'line', width, height, rounded = 'md', className }: SkeletonProps): JSX.Element {
  const style: CSSProperties = {
    width: width ?? DEFAULT_WIDTH[variant],
    height: height ?? DEFAULT_HEIGHT[variant],
  };

  const classes = ['skeleton-shimmer inline-block shrink-0 align-middle', ROUNDED_CLASSES[rounded], className]
    .filter(Boolean)
    .join(' ');

  return <span aria-hidden="true" data-variant={variant} style={style} className={classes} />;
}
