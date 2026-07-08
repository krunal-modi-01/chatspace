import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { AlertBanner } from '../components/ui/AlertBanner';
import { AuroraBackground } from '../components/ui/AuroraBackground';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { FormField } from '../components/ui/FormField';
import { usePasswordResetRequestForm } from '../hooks/usePasswordResetRequestForm';

/** Request a password reset email. Always shows the uniform confirmation
 * message on success — never reveals whether the email matched an account. */
export function PasswordResetRequestPage(): JSX.Element {
  const { email, setEmail, error, isSubmitting, message, submit } = usePasswordResetRequestForm();

  return (
    <AuroraBackground>
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-6">
          <h1 className="text-center text-display text-[var(--color-text-primary)]">Reset your password</h1>

          {error !== null && <ErrorBanner error={error} />}

          {message !== null ? (
            <AlertBanner variant="success">{message}</AlertBanner>
          ) : (
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

                <Button type="submit" isLoading={isSubmitting} loadingText="Sending…">
                  Send reset link
                </Button>
              </form>
            </Card>
          )}

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
