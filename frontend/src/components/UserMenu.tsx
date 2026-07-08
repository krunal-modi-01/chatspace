import { useEffect, useRef, useState, type JSX } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useLogout } from '../hooks/useLogout';

const MENU_ITEM_CLASSES =
  'block w-full px-4 py-2 text-left text-body text-[var(--color-text-primary)] transition-colors ' +
  'duration-150 ease-out hover:bg-[var(--color-surface-raised)] focus-visible:outline-none ' +
  'focus-visible:bg-[var(--color-surface-raised)]';

/** Consolidates "Change password", "Sessions", and "Sign out" behind a
 * single account menu in the app shell nav, rather than four competing
 * top-level items (architecture/design-tokens.md — AppShell redesign). */
export function UserMenu(): JSX.Element {
  const { user } = useAuth();
  const { logoutAndRedirect, isLoggingOut } = useLogout();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent): void {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  const initial = (user?.username ?? '?').slice(0, 1).toUpperCase();

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-body font-medium text-[var(--color-text-primary)] transition-colors duration-150 ease-out hover:bg-[var(--color-surface-overlay)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--color-accent)]/15 text-caption font-semibold text-[var(--color-accent)]">
          {initial}
        </span>
        {user && <span>{user.username}</span>}
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
          className={`h-3.5 w-3.5 text-[var(--color-text-tertiary)] transition-transform duration-150 ease-out ${isOpen ? 'rotate-180' : ''}`}
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.24 4.5a.75.75 0 01-1.08 0l-4.24-4.5a.75.75 0 01.02-1.06z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <div
          role="menu"
          aria-label="Account menu"
          className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)] py-1 shadow-sm"
        >
          <Link
            role="menuitem"
            to="/settings/password"
            onClick={() => setIsOpen(false)}
            className={MENU_ITEM_CLASSES}
          >
            Change password
          </Link>
          <Link
            role="menuitem"
            to="/settings/sessions"
            onClick={() => setIsOpen(false)}
            className={MENU_ITEM_CLASSES}
          >
            Sessions
          </Link>
          <div role="separator" className="my-1 border-t border-[var(--color-border)]" />
          <button
            role="menuitem"
            type="button"
            onClick={logoutAndRedirect}
            disabled={isLoggingOut}
            className={`${MENU_ITEM_CLASSES} text-[var(--color-danger)] disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      )}
    </div>
  );
}
