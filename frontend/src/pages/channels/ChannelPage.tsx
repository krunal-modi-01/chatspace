import { useState, type JSX } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ErrorBanner } from '../../components/ErrorBanner';
import { MessageList } from '../../components/chat/MessageList';
import { PresenceIndicator } from '../../components/chat/PresenceIndicator';
import { AlertBanner } from '../../components/ui/AlertBanner';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { FormField } from '../../components/ui/FormField';
import { Select } from '../../components/ui/Select';
import { useAuth } from '../../hooks/useAuth';
import { useChannelDetail } from '../../hooks/useChannelDetail';
import { useChannelRemovalNotice } from '../../hooks/useChannelRemovalNotice';
import { useConversationSocket } from '../../hooks/useConversationSocket';
import { usePresenceAndTyping } from '../../hooks/usePresenceAndTyping';
import { ApiError } from '../../api/problem';
import { channelRoleBadgeVariant } from '../../utils/channelRoleBadgeVariant';
import type { ChannelMember, ChannelRole, ConversationTarget } from '../../api/types';
import type { PresenceState } from '../../ws/presenceStore';

/** Maps the zero-admin-frozen 409 to the spec's exact affordance copy;
 * falls back to the generic `ErrorBanner` for anything else. */
function mutationErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 409) {
    return 'This channel currently has no admins — membership changes are blocked.';
  }
  return null;
}

/** A pending self-targeted mutation awaiting a second, explicit confirm click
 * — mirrors the Leave-channel two-step confirm so an admin can't silently
 * demote/remove themselves (and possibly trigger the F37 zero-admin frozen
 * state) with a single misclick, the way the non-self controls allow. */
type PendingSelfAction = { type: 'role'; role: ChannelRole } | { type: 'remove' };

function MemberRow({
  member,
  isSelf,
  isCallerAdmin,
  isFrozen,
  isBusy,
  presence,
  pendingSelfAction,
  onRequestRoleChange,
  onRequestRemove,
  onConfirmSelfAction,
  onCancelSelfAction,
}: {
  member: ChannelMember;
  isSelf: boolean;
  isCallerAdmin: boolean;
  isFrozen: boolean;
  isBusy: boolean;
  presence: PresenceState | undefined;
  pendingSelfAction: PendingSelfAction | null;
  onRequestRoleChange: (userId: string, role: ChannelRole) => void;
  onRequestRemove: (userId: string) => void;
  onConfirmSelfAction: () => void;
  onCancelSelfAction: () => void;
}): JSX.Element {
  const hasPendingSelfAction = isSelf && pendingSelfAction !== null;

  return (
    <tr className="border-b border-[var(--color-border)] last:border-0">
      <td className="px-4 py-3 text-body text-[var(--color-text-primary)]">
        {member.first_name} {member.last_name}
        {isSelf && <span className="ml-1 text-caption text-[var(--color-text-tertiary)]">(you)</span>}
        <div className="text-caption text-[var(--color-text-tertiary)]">@{member.username}</div>
        <PresenceIndicator presence={presence} />
      </td>
      <td className="px-4 py-3">
        {isCallerAdmin ? (
          <label>
            <span className="sr-only">
              Role for {member.first_name} {member.last_name}
            </span>
            <Select
              value={member.role === 'admin' ? 'admin' : 'member'}
              disabled={isFrozen || isBusy || hasPendingSelfAction}
              onChange={(event) => onRequestRoleChange(member.user_id, event.target.value)}
              className="mt-0 w-32"
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
            </Select>
          </label>
        ) : (
          <Badge variant={channelRoleBadgeVariant(member.role)} className="capitalize">
            {member.role}
          </Badge>
        )}
      </td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)]">
        {new Date(member.joined_at).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-right">
        {isCallerAdmin &&
          (hasPendingSelfAction ? (
            <div className="flex items-center justify-end gap-2">
              <span className="text-caption text-[var(--color-danger)]">
                {pendingSelfAction?.type === 'role'
                  ? `Change your own role to ${pendingSelfAction.role}?`
                  : 'Remove yourself from this channel?'}
              </span>
              <Button
                type="button"
                variant="danger"
                size="sm"
                isLoading={isBusy}
                loadingText="Confirming…"
                onClick={onConfirmSelfAction}
              >
                Confirm
              </Button>
              <Button type="button" variant="secondary" size="sm" disabled={isBusy} onClick={onCancelSelfAction}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={isBusy}
              loadingText="Removing…"
              disabled={isFrozen}
              onClick={() => onRequestRemove(member.user_id)}
            >
              Remove
            </Button>
          ))}
      </td>
    </tr>
  );
}

/** Channel view screen (T31): detail header, member list, admin-only
 * membership management, leave with succession messaging, and the
 * zero-admin frozen-state affordance. Messages are out of scope (T32).
 *
 * Keyed by `channelId` below so that navigating directly between two
 * `/channels/:channelId` routes fully remounts (and resets) all local view
 * state rather than carrying over stale `isFrozen`/member-list/confirm state
 * from the previously viewed channel. */
export function ChannelPage(): JSX.Element {
  const { channelId } = useParams<{ channelId: string }>();
  return <ChannelPageForId key={channelId ?? ''} channelId={channelId ?? ''} />;
}

function ChannelPageForId({ channelId }: { channelId: string }): JSX.Element {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [isConfirmingLeave, setIsConfirmingLeave] = useState(false);
  const [pendingSelfAction, setPendingSelfAction] = useState<PendingSelfAction | null>(null);
  const { wasRemoved, dismiss: dismissRemovalNotice } = useChannelRemovalNotice(channelId);

  const {
    channel,
    isLoadingChannel,
    channelError,
    members,
    membersTotal,
    membersOffset,
    membersPageSize,
    isLoadingMembers,
    membersError,
    isFrozen,
    isSoleVisibleAdmin,
    join,
    isJoining,
    joinError,
    leave,
    isLeaving,
    leaveError,
    actionUserId,
    actionError,
    changeRole,
    removeMember,
    addUserId,
    setAddUserId,
    addRole,
    setAddRole,
    isAdding,
    addError,
    addMember,
    hasNextMembersPage,
    hasPreviousMembersPage,
    nextMembersPage,
    previousMembersPage,
  } = useChannelDetail(channelId);

  // Computed defensively against a possibly-still-loading/null `channel`
  // (must be called unconditionally, before the early returns below, per
  // the Rules of Hooks) — only an actual member is authorized to join this
  // conversation's WS topic (`authorize_conversation`, backend), so this
  // stays `null` (no connection attempted) until membership is confirmed.
  const conversationTarget: ConversationTarget | null =
    channel !== null && channel.my_role !== null ? { kind: 'channel', channel_id: channelId } : null;
  const {
    status: wsStatus,
    typingUserIds,
    presenceByUserId,
    sendTyping,
  } = usePresenceAndTyping(conversationTarget);

  // Separate connection from `usePresenceAndTyping` above, by design for
  // now (T51 integration) — see that hook's docstring for why the two
  // aren't yet consolidated into a single socket. This one supplies the
  // live `message.created/edited/deleted` events `MessageList` was
  // otherwise missing entirely (it previously only ever rendered REST
  // history, so other members' messages required a page refresh to
  // appear).
  const { messages: liveMessages } = useConversationSocket(conversationTarget);

  // Live `channel.member_removed` for the channel currently open (F75, Flow
  // L step 4a) — takes priority over every other state below since the
  // caller's membership (and therefore the rest of this view) is gone.
  if (wasRemoved) {
    return (
      <div className="max-w-3xl space-y-4">
        <AlertBanner variant="warning" title="You were removed from this channel">
          You no longer have access to this channel&apos;s messages or members. If this was a mistake, ask a channel
          admin to re-add you.
        </AlertBanner>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            dismissRemovalNotice();
            navigate('/channels');
          }}
        >
          Back to channels
        </Button>
      </div>
    );
  }

  if (isLoadingChannel) {
    return (
      <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
        Loading channel…
      </div>
    );
  }

  if (channelError !== null || channel === null) {
    return (
      <div className="max-w-3xl space-y-4">
        <ErrorBanner error={channelError} />
        <Button type="button" variant="secondary" onClick={() => navigate('/channels')}>
          Back to channels
        </Button>
      </div>
    );
  }

  const isMember = channel.my_role !== null;
  const isCallerAdmin = channel.my_role === 'admin';
  const actionMessage = mutationErrorMessage(actionError);
  const addMessage = mutationErrorMessage(addError);

  const handleLeave = async () => {
    const left = await leave();
    setIsConfirmingLeave(false);
    if (left) {
      navigate('/channels');
    }
  };

  // Self-targeted role-change/remove requires the same two-step confirm as
  // Leave: a single misclick on your own role `<select>` or Remove button
  // can otherwise silently produce the zero-admin frozen state (the backend
  // deliberately skips succession on a self-demotion), with no server-side
  // safety net beyond the eventual 409.
  const handleRequestRoleChange = (userId: string, role: ChannelRole) => {
    if (userId === user?.id) {
      setPendingSelfAction({ type: 'role', role });
      return;
    }
    changeRole(userId, role);
  };

  const handleRequestRemove = (userId: string) => {
    if (userId === user?.id) {
      setPendingSelfAction({ type: 'remove' });
      return;
    }
    removeMember(userId);
  };

  const handleConfirmSelfAction = () => {
    if (!pendingSelfAction || !user) {
      return;
    }
    if (pendingSelfAction.type === 'role') {
      changeRole(user.id, pendingSelfAction.role);
    } else {
      removeMember(user.id);
    }
    setPendingSelfAction(null);
  };

  const handleCancelSelfAction = () => setPendingSelfAction(null);

  const rangeStart = membersTotal === 0 ? 0 : membersOffset + 1;
  const rangeEnd = Math.min(membersOffset + membersPageSize, membersTotal);

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-heading text-[var(--color-text-primary)]">{channel.name}</h1>
          <div className="mt-1 flex items-center gap-2 text-caption text-[var(--color-text-tertiary)]">
            <Badge variant="neutral">{channel.is_private ? 'Private' : 'Public'}</Badge>
            <span>
              {channel.member_count} {channel.member_count === 1 ? 'member' : 'members'}
            </span>
            {channel.my_role !== null && (
              <Badge variant={channelRoleBadgeVariant(channel.my_role)} className="capitalize">
                {channel.my_role}
              </Badge>
            )}
          </div>
        </div>

        {isMember ? (
          isConfirmingLeave ? (
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="danger"
                isLoading={isLeaving}
                loadingText="Leaving…"
                onClick={handleLeave}
              >
                Confirm leave
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={isLeaving}
                onClick={() => setIsConfirmingLeave(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button type="button" variant="secondary" onClick={() => setIsConfirmingLeave(true)}>
              Leave channel
            </Button>
          )
        ) : (
          <Button type="button" isLoading={isJoining} loadingText="Joining…" onClick={() => join()}>
            Join channel
          </Button>
        )}
      </div>

      {isConfirmingLeave && (
        <AlertBanner variant="warning">
          {isSoleVisibleAdmin
            ? "You're the only admin of this channel. If other members remain, one of them will automatically become admin when you leave; if none remain, the channel will keep no admins going forward."
            : "You'll lose access to this channel's messages until you rejoin (public) or are re-added by an admin (private)."}
        </AlertBanner>
      )}

      {leaveError !== null && <ErrorBanner error={leaveError} />}
      {joinError !== null && <ErrorBanner error={joinError} />}

      {isFrozen && (
        <AlertBanner variant="warning" title="No admins">
          This channel currently has no admins. Adding, removing, or changing members is blocked until it has one
          again.
        </AlertBanner>
      )}

      {!isMember ? (
        <Card className="text-body text-[var(--color-text-secondary)]">
          You're not a member of this channel yet — join it to see its members.
        </Card>
      ) : (
        <>
          <h2 className="text-subheading text-[var(--color-text-primary)]">Members</h2>

          {membersError !== null && <ErrorBanner error={membersError} />}
          {actionError !== null &&
            (actionMessage !== null ? (
              <AlertBanner variant="error">{actionMessage}</AlertBanner>
            ) : (
              <ErrorBanner error={actionError} />
            ))}

          {isCallerAdmin && isSoleVisibleAdmin && !isFrozen && (
            <AlertBanner variant="info">
              You're the only visible admin. Demoting or removing yourself may leave this channel without any admins.
            </AlertBanner>
          )}

          {isLoadingMembers ? (
            <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
              Loading members…
            </div>
          ) : members.length === 0 ? (
            <Card className="text-body text-[var(--color-text-secondary)]">No members found.</Card>
          ) : (
            <>
              <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)]">
                <table className="w-full text-left">
                  <caption className="sr-only">Channel members</caption>
                  <thead>
                    <tr className="border-b border-[var(--color-border)] text-caption font-semibold text-[var(--color-text-tertiary)]">
                      <th scope="col" className="px-4 py-2">
                        Name
                      </th>
                      <th scope="col" className="px-4 py-2">
                        Role
                      </th>
                      <th scope="col" className="px-4 py-2">
                        Joined
                      </th>
                      <th scope="col" className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((member) => (
                      <MemberRow
                        key={member.user_id}
                        member={member}
                        isSelf={member.user_id === user?.id}
                        isCallerAdmin={isCallerAdmin}
                        isFrozen={isFrozen}
                        isBusy={actionUserId === member.user_id}
                        presence={presenceByUserId.get(member.user_id)}
                        pendingSelfAction={member.user_id === user?.id ? pendingSelfAction : null}
                        onRequestRoleChange={handleRequestRoleChange}
                        onRequestRemove={handleRequestRemove}
                        onConfirmSelfAction={handleConfirmSelfAction}
                        onCancelSelfAction={handleCancelSelfAction}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between text-body text-[var(--color-text-secondary)]">
                <span>
                  Showing {rangeStart}-{rangeEnd} of {membersTotal}
                </span>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={!hasPreviousMembersPage}
                    onClick={previousMembersPage}
                  >
                    Previous
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={!hasNextMembersPage}
                    onClick={nextMembersPage}
                  >
                    Next
                  </Button>
                </div>
              </div>
            </>
          )}

          {isCallerAdmin && (
            <Card>
              <h2 className="text-subheading text-[var(--color-text-primary)]">Add a member</h2>
              <p className="mt-1 text-caption text-[var(--color-text-tertiary)]">
                Enter the exact user ID to add — this is the only way into a private channel.
              </p>
              <form className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end" onSubmit={addMember} noValidate>
                <div className="flex-1">
                  <FormField
                    id="add-member-user-id"
                    name="user_id"
                    label="User ID"
                    autoComplete="off"
                    required
                    disabled={isFrozen}
                    value={addUserId}
                    onChange={(event) => setAddUserId(event.target.value)}
                  />
                </div>
                <label className="flex flex-col gap-1 text-body text-[var(--color-text-primary)]">
                  Role
                  <Select
                    value={addRole === 'admin' ? 'admin' : 'member'}
                    disabled={isFrozen}
                    onChange={(event) => setAddRole(event.target.value)}
                    className="w-32"
                  >
                    <option value="member">member</option>
                    <option value="admin">admin</option>
                  </Select>
                </label>
                <Button type="submit" isLoading={isAdding} loadingText="Adding…" disabled={isFrozen}>
                  Add member
                </Button>
              </form>
              {addError !== null &&
                (addMessage !== null ? (
                  <div className="mt-4">
                    <AlertBanner variant="error">{addMessage}</AlertBanner>
                  </div>
                ) : (
                  <div className="mt-4">
                    <ErrorBanner error={addError} />
                  </div>
                ))}
            </Card>
          )}
        </>
      )}

      {isMember && (
        <Card className="flex h-[32rem] flex-col">
          <h2 className="text-subheading text-[var(--color-text-primary)]">Messages</h2>
          <div className="mt-4 flex-1 overflow-hidden">
            <MessageList
              channelId={channelId}
              typingUserIds={typingUserIds}
              onTyping={sendTyping}
              wsStatus={wsStatus}
              liveMessages={liveMessages}
            />
          </div>
        </Card>
      )}
    </div>
  );
}
