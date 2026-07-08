import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-center text-2xl font-semibold text-gray-900">Sign in to chatspace</h1>

        {error !== null && mustChangePassword && (
          <div
            role="alert"
            className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
          >
            <p className="font-medium">Your password must be changed before you can log in.</p>
            <p>
              <Link to="/password-reset" className="font-medium text-indigo-600 hover:text-indigo-500">
                Reset your password
              </Link>{' '}
              to continue.
            </p>
          </div>
        )}
        {error !== null && !mustChangePassword && <ErrorBanner error={error} />}

        <form className="space-y-4" onSubmit={submit} noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="text-right">
            <Link
              to="/password-reset"
              className="text-sm font-medium text-indigo-600 hover:text-indigo-500"
            >
              Forgot password?
            </Link>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500">
          Need an account? Use your invite link to{' '}
          <Link to="/register" className="font-medium text-indigo-600 hover:text-indigo-500">
            register
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
