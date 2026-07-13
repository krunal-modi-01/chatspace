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
// Messaging / WebSocket (T33) — channel & DM history + live event payloads.
// ---------------------------------------------------------------------------

/** Discriminated conversation target shared by REST history lookups, WS
 * `join`/`leave` frames, and WS event envelopes. */
export type ConversationTarget =
  | { kind: 'channel'; channel_id: string }
  | { kind: 'dm'; user_id: string };

/** `media[]` entry embedded on a message per the frozen contract — no URL,
 * no dimensions (fetched separately via `GET /v1/media/{media_id}/url`, T28,
 * out of scope here). */
export interface MessageMedia {
  media_id: string;
  kind: string;
  filename: string;
  size: number;
}

/** A message row as returned by history endpoints and WS
 * `message.created`/`message.edited` payloads. `id` is a UUIDv7 — the
 * time-sortable client dedup key and ordering key (F54). */
export interface Message {
  id: string;
  channel_id: string | null;
  recipient_id: string | null;
  sender_id: string;
  content: string;
  media: MessageMedia[];
  created_at: string;
  edited_at: string | null;
  deleted_at: string | null;
}

export interface ListMessagesParams {
  limit?: number;
  cursor?: string | null;
}

// ---------------------------------------------------------------------------
// Channels & membership (T31) — create/browse/join/leave + admin membership
// management. Messages are out of scope here (T32).
// ---------------------------------------------------------------------------

/** Per-channel role — open enum server-side (cross-cutting contract
 * convention: clients must tolerate unknown `role` values). */
export type ChannelRole = 'member' | 'admin' | (string & {});

export interface CreateChannelRequest {
  name: string;
  is_private: boolean;
}

/** `201` body of `POST /v1/channels` — no `my_role` (only `GET /{id}` adds it). */
export interface CreateChannelResponse {
  id: string;
  name: string;
  is_private: boolean;
  created_by: string;
  created_at: string;
  member_count: number;
}

/** One entry of `GET /v1/channels/public`'s `items` — public channels the
 * caller is not yet a member of. */
export interface PublicChannelSummary {
  id: string;
  name: string;
  is_private: false;
  member_count: number;
}

export interface ListPublicChannelsParams {
  limit?: number;
  offset?: number;
}

/** `200` body of `GET /v1/channels/{channel_id}`. `my_role` is `null` for a
 * non-member viewing a public channel (a private channel a non-member
 * cannot see 404s uniformly instead) and drives the admin-affordance UI. */
export interface ChannelDetail {
  id: string;
  name: string;
  is_private: boolean;
  created_by: string;
  created_at: string;
  member_count: number;
  my_role: ChannelRole | null;
}

/** `200` body shared by join / admin-add-member / role-change. */
export interface ChannelMembership {
  channel_id: string;
  user_id: string;
  role: ChannelRole;
  joined_at: string;
}

/** One entry of `GET /v1/channels/{channel_id}/members`'s `items`. */
export interface ChannelMember {
  user_id: string;
  username: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  role: ChannelRole;
  joined_at: string;
}

export interface ListChannelMembersParams {
  limit?: number;
  offset?: number;
}

/** `200` envelope of the member list — `total` only, no echoed
 * `limit`/`offset` (unlike `GET /channels/public`'s envelope). */
export interface ChannelMemberListResponse {
  items: ChannelMember[];
  total: number;
}

export interface AddChannelMemberRequest {
  user_id: string;
  role: ChannelRole;
}

export interface UpdateChannelMemberRoleRequest {
  role: ChannelRole;
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
