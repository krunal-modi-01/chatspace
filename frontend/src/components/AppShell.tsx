import type { JSX } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { ThemeToggle } from './ui/ThemeToggle';
import { UserMenu } from './UserMenu';

const NAV_LINK_CLASSES =
  'rounded-md px-2 py-1.5 text-body font-medium transition-colors duration-150 ease-out ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]';

/** Top-level authenticated shell: brand + primary nav + theme toggle +
 * account menu in the header, and a content outlet for feature screens
 * added in T30+. Stays a flat, neutral surface per
 * architecture/design-tokens.md §1 — no ambient background here, only the
 * elevation treatment from §6. */
export function AppShell(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-[var(--color-surface)]">
      <header className="flex items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface-raised)] px-4 py-3">
        <div className="flex items-center gap-6">
          <span className="text-subheading text-[var(--color-text-primary)]">chatspace</span>
          <nav aria-label="Primary">
            <NavLink
              to="/channels"
              className={({ isActive }) =>
                `${NAV_LINK_CLASSES} ${
                  isActive
                    ? 'text-[var(--color-accent)]'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-overlay)]'
                }`
              }
            >
              Channels
            </NavLink>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>
      <main className="flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
