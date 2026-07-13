import type { JSX } from 'react';

export interface AvatarProps {
  firstName?: string | null;
  lastName?: string | null;
  username?: string | null;
  avatarUrl?: string | null;
  size?: 'sm' | 'md';
}

const SIZE_CLASSES: Record<NonNullable<AvatarProps['size']>, string> = {
  sm: 'h-6 w-6 text-[0.65rem]',
  md: 'h-8 w-8 text-caption',
};

function initialsFrom(firstName?: string | null, lastName?: string | null, username?: string | null): string {
  const first = firstName?.trim().charAt(0);
  const last = lastName?.trim().charAt(0);
  if (first || last) {
    return `${first ?? ''}${last ?? ''}`.toUpperCase();
  }
  const fallback = username?.trim().charAt(0);
  return (fallback || '?').toUpperCase();
}

/** Identity chrome shared across the app (message author badge, member
 * lists, etc.) — image when `avatar_url` is set, initials fallback
 * otherwise (R28: `avatar_url IS NULL` → initials fallback). */
export function Avatar({ firstName, lastName, username, avatarUrl, size = 'md' }: AvatarProps): JSX.Element {
  const sizeClasses = SIZE_CLASSES[size];
  const label = [firstName, lastName].filter(Boolean).join(' ') || username || 'Unknown user';

  if (avatarUrl) {
    return <img src={avatarUrl} alt={label} className={`${sizeClasses} shrink-0 rounded-full object-cover`} />;
  }

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`flex ${sizeClasses} shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)]/15 font-semibold text-[var(--color-accent)]`}
    >
      {initialsFrom(firstName, lastName, username)}
    </span>
  );
}
