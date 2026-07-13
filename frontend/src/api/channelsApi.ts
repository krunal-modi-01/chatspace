import { apiRequest } from './httpClient';
import type { ChannelMemberListResponse } from './types';

/**
 * Minimal slice of the channel-membership contract needed by T32 (messaging
 * UI) to resolve "other user" identity — display name/initials/avatar — for
 * a message's `sender_id`. There is no dedicated user-lookup endpoint in
 * T32's scope; the member list (owned by T31) is the only source, per the
 * frozen contract's explicit guidance. Full channel CRUD/membership
 * management (create/join/leave/role-change) is T31's own scope and is not
 * duplicated here.
 */
export function fetchChannelMembers(
  channelId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ChannelMemberListResponse> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set('limit', String(params.limit));
  }
  if (params.offset !== undefined) {
    search.set('offset', String(params.offset));
  }
  const query = search.toString();
  return apiRequest<ChannelMemberListResponse>(
    `/channels/${encodeURIComponent(channelId)}/members${query ? `?${query}` : ''}`,
    { method: 'GET' },
  );
}
