import { useEffect, useRef, useState, type JSX } from 'react';
import { ErrorBanner } from '../../components/ErrorBanner';
import { AlertBanner } from '../../components/ui/AlertBanner';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { useAdminUsers } from '../../hooks/useAdminUsers';
import { ApiError } from '../../api/problem';
import type { AdminUser } from '../../api/types';

/** Maps the last-active-System-Admin deactivation guard to the exact copy
 * the spec calls for; falls back to the generic `ErrorBanner` for anything
 * else. */
function deactivateErrorMessage(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 409) {
    return 'The workspace must keep at least one active admin.';
  }
  return null;
}

function UserRow({
  user,
  isBusy,
  isConfirming,
  onRequestDeactivate,
  onCancelDeactivate,
  onConfirmDeactivate,
  onReactivate,
  registerActionRef,
}: {
  user: AdminUser;
  isBusy: boolean;
  isConfirming: boolean;
  onRequestDeactivate: (id: string) => void;
  onCancelDeactivate: (id: string) => void;
  onConfirmDeactivate: (id: string) => void;
  onReactivate: (id: string) => void;
  registerActionRef: (id: string, el: HTMLButtonElement | null) => void;
}): JSX.Element {
  return (
    <tr className="border-b border-[var(--color-border)] last:border-0">
      <td className="px-4 py-3 text-body text-[var(--color-text-primary)]">
        {user.first_name} {user.last_name}
      </td>
      <td className="px-4 py-3 text-body text-[var(--color-text-secondary)]">{user.username}</td>
      <td className="px-4 py-3 text-body text-[var(--color-text-secondary)]">{user.email}</td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)] capitalize">
        {user.role.replace('_', ' ')}
      </td>
      <td className="px-4 py-3">
        <Badge variant={user.is_active ? 'success' : 'neutral'}>{user.is_active ? 'Active' : 'Inactive'}</Badge>
      </td>
      <td className="px-4 py-3 text-caption text-[var(--color-text-tertiary)]">
        {user.last_seen ? new Date(user.last_seen).toLocaleString() : 'Never'}
      </td>
      <td className="px-4 py-3 text-right">
        {user.is_active ? (
          isConfirming ? (
            <div className="flex justify-end items-center gap-2">
              <span className="text-caption text-[var(--color-text-secondary)]">Deactivate this user?</span>
              <Button
                ref={(el) => registerActionRef(user.id, el)}
                type="button"
                variant="danger"
                size="sm"
                isLoading={isBusy}
                loadingText="Deactivating…"
                onClick={() => onConfirmDeactivate(user.id)}
              >
                Confirm
              </Button>
              <Button type="button" variant="secondary" size="sm" disabled={isBusy} onClick={() => onCancelDeactivate(user.id)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              ref={(el) => registerActionRef(user.id, el)}
              type="button"
              variant="danger"
              size="sm"
              onClick={() => onRequestDeactivate(user.id)}
            >
              Deactivate
            </Button>
          )
        ) : (
          <Button
            ref={(el) => registerActionRef(user.id, el)}
            type="button"
            variant="secondary"
            size="sm"
            isLoading={isBusy}
            loadingText="Reactivating…"
            onClick={() => onReactivate(user.id)}
          >
            Reactivate
          </Button>
        )}
      </td>
    </tr>
  );
}

/** System Admin screen: search users and deactivate/reactivate accounts.
 * Deactivation requires an explicit inline confirmation. Deactivated users
 * remain visible in the list. Role/route access is gated upstream by
 * `AdminRoute`. */
export function UsersPage(): JSX.Element {
  const { query, setQuery, users, isLoading, listError, search, actionId, actionError, deactivate, reactivate } =
    useAdminUsers();
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const deactivateMessage = deactivateErrorMessage(actionError);

  // Row actions swap one button for another in place (Deactivate -> Confirm,
  // Confirm -> Reactivate, etc.). React mounts a *new* button element each
  // time, so focus is not preserved automatically and falls back to <body>
  // without this — disorienting keyboard/AT users mid-flow.
  const actionButtonRefs = useRef(new Map<string, HTMLButtonElement>());
  const pendingFocusIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (pendingFocusIdRef.current === null) {
      return;
    }
    const id = pendingFocusIdRef.current;
    pendingFocusIdRef.current = null;
    actionButtonRefs.current.get(id)?.focus();
  });

  const registerActionRef = (id: string, el: HTMLButtonElement | null) => {
    if (el) {
      actionButtonRefs.current.set(id, el);
    } else {
      actionButtonRefs.current.delete(id);
    }
  };

  const handleRequestDeactivate = (id: string) => {
    pendingFocusIdRef.current = id;
    setConfirmingId(id);
  };

  const handleCancelDeactivate = (id: string) => {
    pendingFocusIdRef.current = id;
    setConfirmingId(null);
  };

  const handleConfirmDeactivate = async (id: string) => {
    pendingFocusIdRef.current = id;
    await deactivate(id);
    setConfirmingId(null);
  };

  const handleReactivate = async (id: string) => {
    pendingFocusIdRef.current = id;
    await reactivate(id);
  };

  return (
    <div className="max-w-5xl space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">User management</h1>

      <Card>
        <form className="flex gap-3" onSubmit={search}>
          <div className="flex-1">
            <label htmlFor="user-search" className="sr-only">
              Search users
            </label>
            <Input
              id="user-search"
              type="search"
              placeholder="Search by name, username, or email"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="mt-0"
            />
          </div>
          <Button type="submit" variant="secondary">
            Search
          </Button>
        </form>
      </Card>

      {listError !== null && <ErrorBanner error={listError} />}
      {actionError !== null &&
        (deactivateMessage !== null ? (
          <AlertBanner variant="error">{deactivateMessage}</AlertBanner>
        ) : (
          <ErrorBanner error={actionError} />
        ))}

      {isLoading ? (
        <div role="status" aria-live="polite" className="text-body text-[var(--color-text-secondary)]">
          Loading users…
        </div>
      ) : users.length === 0 ? (
        <Card className="text-body text-[var(--color-text-secondary)]">
          {query.trim() ? 'No users found.' : 'No users yet.'}
        </Card>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-overlay)]">
          <table className="w-full text-left">
            <caption className="sr-only">Workspace users</caption>
            <thead>
              <tr className="border-b border-[var(--color-border)] text-caption font-semibold text-[var(--color-text-tertiary)]">
                <th scope="col" className="px-4 py-2">
                  Name
                </th>
                <th scope="col" className="px-4 py-2">
                  Username
                </th>
                <th scope="col" className="px-4 py-2">
                  Email
                </th>
                <th scope="col" className="px-4 py-2">
                  Role
                </th>
                <th scope="col" className="px-4 py-2">
                  Status
                </th>
                <th scope="col" className="px-4 py-2">
                  Last seen
                </th>
                <th scope="col" className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  isBusy={actionId === user.id}
                  isConfirming={confirmingId === user.id}
                  onRequestDeactivate={handleRequestDeactivate}
                  onCancelDeactivate={handleCancelDeactivate}
                  onConfirmDeactivate={handleConfirmDeactivate}
                  onReactivate={handleReactivate}
                  registerActionRef={registerActionRef}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
