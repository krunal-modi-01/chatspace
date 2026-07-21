import { useRef, type JSX } from 'react';
import { ErrorBanner } from '../../components/ErrorBanner';
import { AlertBanner } from '../../components/ui/AlertBanner';
import { Badge, type BadgeVariant } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { FormField } from '../../components/ui/FormField';
import { Select } from '../../components/ui/Select';
import { useInvites } from '../../hooks/useInvites';
import { ApiError } from '../../api/problem';
import type { InviteListItem, InviteStatus } from '../../api/types';

/** Invite status → `Badge` variant (docs/design/DESIGN_SYSTEM.md §3.2:
 * `pending` → `warning`, `accepted` → `success`, `revoked` → `danger`,
 * `expired` → `neutral`). The token-lifecycle language elsewhere in
 * api-contract.md also surfaces a `used` outcome, and enum-typed fields are
 * documented as open sets clients must tolerate (Conventions) — anything
 * outside the four listed values falls back to `neutral` rather than
 * throwing or rendering unstyled. */
function inviteStatusBadgeVariant(status: InviteStatus): BadgeVariant {
  switch (status) {
    case 'pending':
      return 'warning';
    case 'accepted':
      return 'success';
    case 'revoked':
      return 'danger';
    case 'expired':
      return 'neutral';
    default:
      return 'neutral';
  }
}

/** Maps the two invite-issuance error cases the spec calls out by exact
 * copy; falls back to the generic `ErrorBanner` for anything else. */
function issueErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'This email already has an account.';
    if (error.status === 502) return "Invite couldn't be delivered — try again.";
  }
  return null;
}

/** Maps the resend/revoke non-pending error case; falls back to the
 * generic `ErrorBanner` for anything else. */
function actionErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError && (error.status === 409 || error.status === 410)) {
    return 'This invite is no longer pending.';
  }
  return null;
}

function InviteRow({
  invite,
  isBusy,
  onResend,
  onRevoke,
}: {
  invite: InviteListItem;
  isBusy: boolean;
  onResend: (id: string) => void;
  onRevoke: (id: string) => void;
}): JSX.Element {
  return (
    <tr className="border-b border-[var(--color-border)] last:border-0">
      <td className="px-4 py-3 text-body text-[var(--color-text-primary)]">{invite.email}</td>
      <td className="px-4 py-3">
        <Badge variant={inviteStatusBadgeVariant(invite.status)} className="capitalize">
          {invite.status}
        </Badge>
      </td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)]">
        {new Date(invite.issued_at).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)]">
        {new Date(invite.expiry).toLocaleString()}
      </td>
      <td className="px-4 py-3 text-right">
        {invite.status === 'pending' && (
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              isLoading={isBusy}
              loadingText="Resending…"
              onClick={() => onResend(invite.id)}
            >
              Resend
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={isBusy}
              loadingText="Revoking…"
              onClick={() => onRevoke(invite.id)}
            >
              Revoke
            </Button>
          </div>
        )}
      </td>
    </tr>
  );
}

/** System Admin screen: issue invites and manage outstanding ones (resend
 * pending, revoke pending), filterable by status. Role/route access is
 * gated upstream by `AdminRoute`. */
export function InvitesPage(): JSX.Element {
  const {
    statusFilter,
    setStatusFilter,
    invites,
    isLoading,
    listError,
    email,
    setEmail,
    emailError,
    issueError,
    isIssuing,
    submitInvite,
    actionId,
    actionError,
    resend,
    revoke,
  } = useInvites();

  const issueMessage = issueErrorMessage(issueError);
  const actionMessage = actionErrorMessage(actionError);

  const headingRef = useRef<HTMLHeadingElement>(null);

  const handleRevoke = async (id: string) => {
    const succeeded = await revoke(id);
    // Row is removed from the DOM on success — without this, focus would
    // otherwise fall back to <body>, disorienting keyboard/AT users.
    if (succeeded) {
      headingRef.current?.focus();
    }
  };

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">Invite management</h1>

      <Card>
        <form className="flex flex-col gap-4 sm:flex-row sm:items-end" onSubmit={submitInvite} noValidate>
          <div className="flex-1">
            <FormField
              id="invite-email"
              name="email"
              label="Email"
              type="email"
              autoComplete="off"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              error={emailError ?? undefined}
            />
          </div>
          <Button type="submit" isLoading={isIssuing} loadingText="Sending…">
            Send invite
          </Button>
        </form>
        {issueError !== null &&
          (issueMessage !== null ? (
            <div className="mt-4">
              <AlertBanner variant="error">{issueMessage}</AlertBanner>
            </div>
          ) : (
            <div className="mt-4">
              <ErrorBanner error={issueError} />
            </div>
          ))}
      </Card>

      <div className="flex items-center justify-between gap-4">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="text-subheading text-[var(--color-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] rounded-sm"
        >
          Outstanding invites
        </h2>
        <div className="w-48">
          <label htmlFor="invite-status-filter" className="sr-only">
            Filter by status
          </label>
          <Select
            id="invite-status-filter"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
            className="mt-0"
          >
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="revoked">Revoked</option>
            <option value="expired">Expired</option>
          </Select>
        </div>
      </div>

      {listError !== null && <ErrorBanner error={listError} />}
      {actionError !== null &&
        (actionMessage !== null ? (
          <AlertBanner variant="error">{actionMessage}</AlertBanner>
        ) : (
          <ErrorBanner error={actionError} />
        ))}

      {isLoading ? (
        <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
          Loading invites…
        </div>
      ) : invites.length === 0 ? (
        <Card className="text-body text-[var(--color-text-secondary)]">No invites issued yet.</Card>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)]">
          <table className="w-full text-left">
            <caption className="sr-only">Outstanding invites</caption>
            <thead>
              <tr className="border-b border-[var(--color-border)] text-caption font-semibold text-[var(--color-text-tertiary)]">
                <th scope="col" className="px-4 py-2">
                  Email
                </th>
                <th scope="col" className="px-4 py-2">
                  Status
                </th>
                <th scope="col" className="px-4 py-2">
                  Issued
                </th>
                <th scope="col" className="px-4 py-2">
                  Expires
                </th>
                <th scope="col" className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {invites.map((invite) => (
                <InviteRow
                  key={invite.id}
                  invite={invite}
                  isBusy={actionId === invite.id}
                  onResend={resend}
                  onRevoke={handleRevoke}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
