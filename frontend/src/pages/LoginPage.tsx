import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { AlertBanner } from '../components/ui/AlertBanner';
import { AuroraBackground } from '../components/ui/AuroraBackground';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { FormField } from '../components/ui/FormField';
import { isMustChangePasswordError, useLoginForm } from '../hooks/useLoginForm';

/** Login screen wiring the typed API client + auth store. Non-happy states
 * (invalid credentials, deactivated account, must-change-password) surface
 * via the shared `ErrorBanner`/problem+json pattern in `useLoginForm`, except
 * must-change-password which gets a specific message + CTA to the existing
 * self-service password-reset flow (ADR-0011) instead of the generic banner. */
export function LoginPage(): JSX.Element {
  const { email, setEmail, password, setPassword, error, isSubmitting, submit } = useLoginForm();
  const mustChangePassword = isMustChangePasswordError(error);

  return (
    <AuroraBackground>
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-6">
          <h1 className="text-center text-display text-[var(--color-text-primary)]">
            Sign in to chatspace
          </h1>

          {error !== null && mustChangePassword && (
            <AlertBanner variant="warning" title="Your password must be changed before you can log in.">
              <p>
                <Link
                  to="/password-reset"
                  className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]"
                >
                  Reset your password
                </Link>{' '}
                to continue.
              </p>
            </AlertBanner>
          )}
          {error !== null && !mustChangePassword && <ErrorBanner error={error} />}

          <Card>
            <form className="space-y-4" onSubmit={submit} noValidate>
              <FormField
                id="email"
                name="email"
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />

              <FormField
                id="password"
                name="password"
                label="Password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />

              <div className="text-right">
                <Link
                  to="/password-reset"
                  className="text-body font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]"
                >
                  Forgot password?
                </Link>
              </div>

              <Button type="submit" fullWidth isLoading={isSubmitting} loadingText="Signing in…">
                Sign in
              </Button>
            </form>
          </Card>

          <p className="text-center text-body text-[var(--color-text-secondary)]">
            Need an account? Use your invite link to{' '}
            <Link to="/register" className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
              register
            </Link>
            .
          </p>
        </div>
      </div>
    </AuroraBackground>
  );
}
