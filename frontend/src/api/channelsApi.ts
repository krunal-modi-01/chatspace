import { apiRequest } from './httpClient';
import type {
  AddChannelMemberRequest,
  ChannelDetail,
  ChannelMemberListResponse,
  ChannelMembership,
  CreateChannelRequest,
  CreateChannelResponse,
  CursorPage,
  ListChannelMembersParams,
  ListMyChannelsParams,
  ListPublicChannelsParams,
  MyChannelSummary,
  OffsetPage,
  PublicChannelSummary,
  UpdateChannelMemberRoleRequest,
} from './types';

/** Builds a query string from defined params only — omits `limit`/`offset`
 * entirely rather than sending empty values (mirrors `adminApi.ts`). */
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

/** Protected — creates a public or private channel; the creator becomes its
 * first admin (R4). `409` on a case-insensitive name collision, `422` on an
 * invalid name (length/charset). */
export function createChannel(payload: CreateChannelRequest): Promise<CreateChannelResponse> {
  return apiRequest<CreateChannelResponse>('/channels', { method: 'POST', body: payload });
}

/** Protected — cursor-paginated list of every channel (public and private)
 * the caller is a member of; backs the "My Channels" navigation surface
 * (F73, T50). Mirrors `adminApi.listInvites`'s cursor-page shape. Default
 * limit 50, server max 100 (clamped); an empty membership set is a
 * non-error `{ items: [], next_cursor: null }` page. */
export function listMyChannels(params: ListMyChannelsParams = {}): Promise<CursorPage<MyChannelSummary>> {
  return apiRequest<CursorPage<MyChannelSummary>>(`/channels${toQueryString(params)}`, { method: 'GET' });
}

/** Protected — offset-paginated browse of public channels the caller is not
 * yet a member of (F30). Page size default AND max are both 50. */
export function listPublicChannels(
  params: ListPublicChannelsParams = {},
): Promise<OffsetPage<PublicChannelSummary>> {
  return apiRequest<OffsetPage<PublicChannelSummary>>(`/channels/public${toQueryString(params)}`, {
    method: 'GET',
  });
}

/** Protected — channel detail. A non-member of a private channel gets a
 * uniform, non-enumerating `404` (indistinguishable from a missing
 * channel). `my_role` drives the admin-affordance UI. */
export function getChannel(channelId: string): Promise<ChannelDetail> {
  return apiRequest<ChannelDetail>(`/channels/${encodeURIComponent(channelId)}`, { method: 'GET' });
}

/** Protected — joins a public channel directly (F31); idempotent (already a
 * member -> 200, no duplicate). Private channels reject with `403`
 * (join-by-admin only, via `addChannelMember`). */
export function joinChannel(channelId: string): Promise<ChannelMembership> {
  return apiRequest<ChannelMembership>(`/channels/${encodeURIComponent(channelId)}/join`, {
    method: 'POST',
    body: {},
  });
}

/** Protected — leaves a channel; sole-admin succession (or the zero-admin
 * frozen state, F37) is applied server-side but never reported back on this
 * `204` — callers must re-fetch channel/member state to reflect it (frozen
 * contract). Idempotent — a repeat/no-op leave and an absent channel both
 * return `204`. */
export function leaveChannel(channelId: string): Promise<void> {
  return apiRequest<void>(`/channels/${encodeURIComponent(channelId)}/leave`, {
    method: 'POST',
    body: {},
  });
}

/** Protected, member-only — the channel's member list. `403` if the caller
 * is not a member of a (discoverable) public channel; a private channel the
 * caller cannot see is the same uniform `404` as `getChannel`. */
export function listChannelMembers(
  channelId: string,
  params: ListChannelMembersParams = {},
): Promise<ChannelMemberListResponse> {
  return apiRequest<ChannelMemberListResponse>(
    `/channels/${encodeURIComponent(channelId)}/members${toQueryString(params)}`,
    { method: 'GET' },
  );
}

/** Protected, admin-only — adds a member (F32/F33), the only way into a
 * private channel; idempotent (already a member -> 200). `409` if the
 * channel is in the zero-admin frozen state (F37). */
export function addChannelMember(
  channelId: string,
  payload: AddChannelMemberRequest,
): Promise<ChannelMembership> {
  return apiRequest<ChannelMembership>(`/channels/${encodeURIComponent(channelId)}/members`, {
    method: 'POST',
    body: payload,
  });
}

/** Protected, admin-only — changes a member's role; idempotent (setting the
 * current role -> 200). `409` if zero-admin frozen. */
export function updateChannelMemberRole(
  channelId: string,
  userId: string,
  payload: UpdateChannelMemberRoleRequest,
): Promise<ChannelMembership> {
  return apiRequest<ChannelMembership>(
    `/channels/${encodeURIComponent(channelId)}/members/${encodeURIComponent(userId)}`,
    { method: 'PATCH', body: payload },
  );
}

/** Protected, admin-only — removes a member (F33); triggers succession if
 * the target is the channel's sole admin. Idempotent (target not a member
 * -> 204). `409` if zero-admin frozen. */
export function removeChannelMember(channelId: string, userId: string): Promise<void> {
  return apiRequest<void>(`/channels/${encodeURIComponent(channelId)}/members/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });
}

/**
 * Alias of `listChannelMembers` for T32 (messaging UI) call sites that only
 * need the member list to resolve "other user" identity — display
 * name/initials/avatar — for a message's `sender_id`. There is no dedicated
 * user-lookup endpoint; the member list (owned by T31) is the only source,
 * per the frozen contract's explicit guidance.
 */
export function fetchChannelMembers(
  channelId: string,
  params: ListChannelMembersParams = {},
): Promise<ChannelMemberListResponse> {
  return listChannelMembers(channelId, params);
}
