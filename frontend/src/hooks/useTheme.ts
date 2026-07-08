import { useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'chatspace-theme';

function isTheme(value: string | null): value is Theme {
  return value === 'light' || value === 'dark';
}

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    // Storage may be unavailable (private mode, disabled cookies, etc.) —
    // fall back to system preference rather than throwing.
    return null;
  }
}

function readSystemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return 'light';
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyThemeClass(theme: Theme): void {
  if (typeof document === 'undefined') {
    return;
  }
  document.documentElement.classList.toggle('dark', theme === 'dark');
}

let currentTheme: Theme = typeof window === 'undefined' ? 'light' : (readStoredTheme() ?? readSystemTheme());
const listeners = new Set<() => void>();

applyThemeClass(currentTheme);

function setTheme(theme: Theme): void {
  currentTheme = theme;
  applyThemeClass(theme);
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Best-effort persistence only.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): Theme {
  return currentTheme;
}

function getServerSnapshot(): Theme {
  return 'light';
}

export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

/** App-wide light/dark theme state (architecture/design-tokens.md §7).
 * Defaults to `prefers-color-scheme` on first load, persisted to
 * `localStorage`, and applied as a `dark` class on `<html>` so Tailwind's
 * class-based `dark:` variant (and the CSS variable overrides in
 * `index.css`) pick it up. Backed by a module-level store rather than
 * context — there is exactly one document-wide toggle. */
export function useTheme(): UseThemeResult {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  return {
    theme,
    setTheme,
    toggleTheme: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
  };
}
