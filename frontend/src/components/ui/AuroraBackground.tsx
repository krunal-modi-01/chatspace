import type { JSX, ReactNode } from 'react';

export interface AuroraBackgroundProps {
  children: ReactNode;
}

/** Ambient gradient + noise wrapper for auth/onboarding surfaces only
 * (architecture/design-tokens.md §3). Never used in the working app shell —
 * the dashboard/nav stay flat per §1. Blobs are off-axis and asymmetrical on
 * purpose, to avoid a centered "spotlight" look. */
export function AuroraBackground({ children }: AuroraBackgroundProps): JSX.Element {
  return (
    <div className="relative min-h-screen overflow-hidden bg-[var(--color-surface)]">
      <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 -left-24 h-[70vh] w-[70vh] rounded-full bg-indigo-500/15 blur-3xl dark:bg-indigo-400/15" />
        <div className="absolute top-1/4 -right-32 h-[60vh] w-[60vh] rounded-full bg-violet-500/15 blur-3xl dark:bg-violet-400/10" />
        <div className="absolute -bottom-40 left-1/3 h-[65vh] w-[65vh] rounded-full bg-indigo-400/10 blur-3xl dark:bg-indigo-300/10" />
        <svg className="absolute inset-0 h-full w-full opacity-[0.03]">
          <filter id="aurora-noise">
            <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" stitchTiles="stitch" />
          </filter>
          <rect width="100%" height="100%" filter="url(#aurora-noise)" />
        </svg>
      </div>
      <div className="relative z-10">{children}</div>
    </div>
  );
}
