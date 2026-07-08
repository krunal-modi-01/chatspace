import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { AuroraBackground } from '../components/ui/AuroraBackground';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { FormField } from '../components/ui/FormField';
import { usePasswordResetConfirmForm } from '../hooks/usePasswordResetConfirmForm';

/** Sets a new password from a reset-link token. Renders a clear "link
 * expired, request a new one" message for a stale/used/unknown token. */
export function PasswordResetConfirmPage(): JSX.Element {
  const { newPassword, setNewPassword, error, isSubmitting, isTokenStale, submit } =
    usePasswordResetConfirmForm();

  if (isTokenStale) {
    return (
      <AuroraBackground>
        <div className="flex min-h-screen items-center justify-center px-4">
          <div className="w-full max-w-sm space-y-4 text-center">
            <h1 className="text-display text-[var(--color-text-primary)]">Reset link expired</h1>
            <p className="text-body text-[var(--color-text-secondary)]">
              This password reset link is expired, already used, or no longer valid. Please request a
              new one.
            </p>
            <Link
              to="/password-reset"
              className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]"
            >
              Request a new reset link
            </Link>
          </div>
        </div>
      </AuroraBackground>
    );
  }

  return (
    <AuroraBackground>
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-6">
          <h1 className="text-center text-display text-[var(--color-text-primary)]">Choose a new password</h1>

          {error !== null && <ErrorBanner error={error} />}

          <Card>
            <form className="space-y-4" onSubmit={submit} noValidate>
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
                Set new password
              </Button>
            </form>
          </Card>

          <p className="text-center text-body text-[var(--color-text-secondary)]">
            <Link to="/login" className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
              Back to sign in
            </Link>
          </p>
        </div>
      </div>
    </AuroraBackground>
  );
}
