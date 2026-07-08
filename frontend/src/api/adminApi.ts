import { apiRequest } from './httpClient';
import type {
  AdminUser,
  AdminUserActivationResponse,
  CursorPage,
  Invite,
  InviteListItem,
  IssueInviteRequest,
  ListAdminUsersParams,
  ListInvitesParams,
} from './types';

/** Builds a query string from defined, non-empty params only — omits
 * `status`/`q`/`cursor` entirely rather than sending empty values. */
function toQueryString(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

/** Protected, system_admin-only — issues a single-use invite by email. */
export function issueInvite(payload: IssueInviteRequest): Promise<Invite> {
  return apiRequest<Invite>('/invites', { method: 'POST', body: payload });
}

/** Protected, system_admin-only — paginated invite list, optionally
 * filtered by status. */
export function listInvites(params: ListInvitesParams = {}): Promise<CursorPage<InviteListItem>> {
  return apiRequest<CursorPage<InviteListItem>>(`/invites${toQueryString(params)}`, { method: 'GET' });
}

/** Protected, system_admin-only — rotates the token for a pending invite;
 * 409 if the invite is no longer pending. */
export function resendInvite(id: string): Promise<Invite> {
  return apiRequest<Invite>(`/invites/${encodeURIComponent(id)}/resend`, {
    method: 'POST',
    body: {},
  });
}

/** Protected, system_admin-only — revokes a pending invite; 409 if already
 * accepted. */
export function revokeInvite(id: string): Promise<void> {
  return apiRequest<void>(`/invites/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** Protected, system_admin-only — paginated, searchable user list. Never
 * returns password material. */
export function listAdminUsers(params: ListAdminUsersParams = {}): Promise<CursorPage<AdminUser>> {
  return apiRequest<CursorPage<AdminUser>>(`/admin/users${toQueryString(params)}`, { method: 'GET' });
}

/** Protected, system_admin-only — deactivates a user, revokes their
 * sessions, and runs sole-admin channel succession. 409 if this would leave
 * the workspace with zero active System Admins. */
export function deactivateUser(id: string): Promise<AdminUserActivationResponse> {
  return apiRequest<AdminUserActivationResponse>(`/admin/users/${encodeURIComponent(id)}/deactivate`, {
    method: 'POST',
    body: {},
  });
}

/** Protected, system_admin-only — reactivates a user (no prior sessions
 * are restored). */
export function reactivateUser(id: string): Promise<AdminUserActivationResponse> {
  return apiRequest<AdminUserActivationResponse>(`/admin/users/${encodeURIComponent(id)}/reactivate`, {
    method: 'POST',
    body: {},
  });
}
