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

/** `200` body of `GET /v1/invites/{token}` — used to pre-fill and lock the
 * registration email. */
export interface InviteTokenValidation {
  email: string;
  expiry: string;
}

export interface PasswordResetRequest {
  email: string;
}

/** `202` uniform envelope — identical whether or not the email exists. */
export interface PasswordResetAcceptedResponse {
  message: string;
}

export interface PasswordResetConfirmRequest {
  reset_token: string;
  new_password: string;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface SessionSummary {
  session_id: string;
  created_at: string;
  last_seen_at: string | null;
  device_label: string | null;
  current: boolean;
}

export interface SessionListResponse {
  items: SessionSummary[];
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

// ---------------------------------------------------------------------------
// Admin surfaces (T45/T46) — invite management + user management.
// ---------------------------------------------------------------------------

export type InviteStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export interface IssueInviteRequest {
  email: string;
}

/** `200`/`201` body of issue/resend — the raw token is never included
 * (server persists only `token_hash`, R24). */
export interface Invite {
  id: string;
  email: string;
  status: InviteStatus;
  expiry: string;
}

/** Row shape returned by `GET /v1/invites` — adds `issued_at`. */
export interface InviteListItem extends Invite {
  issued_at: string;
}

export interface ListInvitesParams {
  status?: InviteStatus;
  limit?: number;
  cursor?: string;
}

/** Row shape returned by `GET /v1/admin/users` — never includes
 * `hashed_password` or any password material. */
export interface AdminUser {
  id: string;
  first_name: string;
  last_name: string;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  last_seen: string | null;
}

export interface ListAdminUsersParams {
  q?: string;
  status?: string;
  limit?: number;
  cursor?: string;
}

/** `200` body of deactivate/reactivate. */
export interface AdminUserActivationResponse {
  id: string;
  is_active: boolean;
}
