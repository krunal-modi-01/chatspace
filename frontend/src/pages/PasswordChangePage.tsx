import type { JSX } from 'react';
import { ErrorBanner } from '../components/ErrorBanner';
import { AlertBanner } from '../components/ui/AlertBanner';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { FormField } from '../components/ui/FormField';
import { usePasswordChangeForm } from '../hooks/usePasswordChangeForm';

/** Authenticated in-app password change. The current session stays valid
 * on success; every other session is revoked server-side. */
export function PasswordChangePage(): JSX.Element {
  const {
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    error,
    isSubmitting,
    succeeded,
    submit,
  } = usePasswordChangeForm();

  return (
    <div className="max-w-sm space-y-6">
      <h1 className="text-heading text-[var(--color-text-primary)]">Change password</h1>

      {error !== null && <ErrorBanner error={error} />}
      {succeeded && (
        <AlertBanner variant="success">
          Your password has been changed. All other sessions have been signed out.
        </AlertBanner>
      )}

      <Card>
        <form className="space-y-4" onSubmit={submit} noValidate>
          <FormField
            id="currentPassword"
            name="currentPassword"
            label="Current password"
            type="password"
            autoComplete="current-password"
            required
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />

          <FormField
            id="newPassword"
            name="newPassword"
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={6}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            hint="At least 6 characters, with at least one letter and one digit."
          />

          <Button type="submit" isLoading={isSubmitting} loadingText="Saving…">
            Change password
          </Button>
        </form>
      </Card>
    </div>
  );
}
