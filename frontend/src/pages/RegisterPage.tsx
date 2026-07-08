import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { AuroraBackground } from '../components/ui/AuroraBackground';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { FormField } from '../components/ui/FormField';
import { useInviteRegistration } from '../hooks/useInviteRegistration';

/** Invite-redemption registration: the invite token is read from the URL
 * query string, the invited email is prefetched and locked (read-only),
 * and the form submits to `POST /v1/auth/register`. */
export function RegisterPage(): JSX.Element {
  const {
    inviteStatus,
    inviteEmail,
    inviteError,
    fields,
    setField,
    submitError,
    isSubmitting,
    submit,
  } = useInviteRegistration();

  if (inviteStatus === 'loading') {
    return (
      <AuroraBackground>
        <div
          role="status"
          aria-live="polite"
          className="flex min-h-screen items-center justify-center px-4"
        >
          <span className="text-body text-[var(--color-text-secondary)]">Checking your invite…</span>
        </div>
      </AuroraBackground>
    );
  }

  if (inviteStatus === 'invalid') {
    return (
      <AuroraBackground>
        <div className="flex min-h-screen items-center justify-center px-4">
          <div className="w-full max-w-sm space-y-4 text-center">
            <h1 className="text-display text-[var(--color-text-primary)]">Invite link no longer valid</h1>
            <p className="text-body text-[var(--color-text-secondary)]">This invite link is no longer valid.</p>
            {inviteError !== null && <ErrorBanner error={inviteError} />}
            <Link to="/login" className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
              Back to sign in
            </Link>
          </div>
        </div>
      </AuroraBackground>
    );
  }

  return (
    <AuroraBackground>
      <div className="flex min-h-screen items-center justify-center px-4 py-8">
        <div className="w-full max-w-sm space-y-6">
          <h1 className="text-center text-display text-[var(--color-text-primary)]">Create your account</h1>

          {submitError !== null && <ErrorBanner error={submitError} />}

          <Card>
            <form className="space-y-4" onSubmit={submit} noValidate>
              <FormField
                id="email"
                name="email"
                label="Email"
                type="email"
                readOnly
                disabled
                value={inviteEmail ?? ''}
              />

              <FormField
                id="username"
                name="username"
                label="Username"
                type="text"
                autoComplete="username"
                required
                minLength={1}
                maxLength={32}
                value={fields.username}
                onChange={(event) => setField('username', event.target.value)}
              />

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  id="firstName"
                  name="firstName"
                  label="First name"
                  type="text"
                  autoComplete="given-name"
                  required
                  value={fields.firstName}
                  onChange={(event) => setField('firstName', event.target.value)}
                />
                <FormField
                  id="lastName"
                  name="lastName"
                  label="Last name"
                  type="text"
                  autoComplete="family-name"
                  required
                  value={fields.lastName}
                  onChange={(event) => setField('lastName', event.target.value)}
                />
              </div>

              <FormField
                id="password"
                name="password"
                label="Password"
                type="password"
                autoComplete="new-password"
                required
                minLength={6}
                value={fields.password}
                onChange={(event) => setField('password', event.target.value)}
                hint="At least 6 characters, with at least one letter and one digit."
              />

              <FormField
                id="avatarUrl"
                name="avatarUrl"
                label={
                  <>
                    Avatar URL{' '}
                    <span className="font-normal text-[var(--color-text-tertiary)]">(optional)</span>
                  </>
                }
                type="url"
                value={fields.avatarUrl}
                onChange={(event) => setField('avatarUrl', event.target.value)}
              />

              <Button type="submit" isLoading={isSubmitting} loadingText="Creating account…">
                Create account
              </Button>
            </form>
          </Card>

          <p className="text-center text-body text-[var(--color-text-secondary)]">
            Already have an account?{' '}
            <Link to="/login" className="font-medium text-[var(--color-accent)] hover:text-[var(--color-accent-hover)]">
              Sign in
            </Link>
            .
          </p>
        </div>
      </div>
    </AuroraBackground>
  );
}
