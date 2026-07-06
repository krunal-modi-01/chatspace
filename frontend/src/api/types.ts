/**
 * Wire-level types for the frozen chatspace v1 API contract.
 * Keep these in sync with `docs/spec/chatspace-v1-api-contract.md` — do not
 * add fields that are not published there.
 */

/** `role` is an open enum server-side (`system_admin` / `user` today) —
 * clients must tolerate unknown values, so it is typed as `string`. */
export type UserRole = 'system_admin' | 'user' | (string & {});

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  role: UserRole;
  is_active: boolean;
  last_seen: string | null;
  created_at: string;
}

export interface RegisteredUser {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  role: UserRole;
  created_at: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface AuthTokens {
  access_token: string;
  token_type: 'Bearer';
  expires_in: number;
}

export interface LoginResponse extends AuthTokens {
  refresh_token: string;
  user: CurrentUser;
}

export interface RefreshRequest {
  refresh_token: string;
}

/** Note: no `user` field on refresh per the frozen contract. */
export interface RefreshResponse extends AuthTokens {
  refresh_token: string;
}

export interface RegisterRequest {
  invite_token: string;
  username: string;
  first_name: string;
  last_name: string;
  password: string;
  avatar_url?: string | null;
}

/** RFC 7807 `application/problem+json` error body. */
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance: string;
  correlation_id: string;
  errors?: Array<{ field: string; detail: string }>;
}

/** Cursor-paged response envelope (message/DM history). The cursor is an
 * opaque base64url token — never construct or decode it client-side. */
export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

/** Offset-paged response envelope (public-channel browse). */
export interface OffsetPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
