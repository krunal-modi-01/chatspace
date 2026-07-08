import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
import { usePasswordResetRequestForm } from '../hooks/usePasswordResetRequestForm';

/** Request a password reset email. Always shows the uniform confirmation
 * message on success — never reveals whether the email matched an account. */
export function PasswordResetRequestPage(): JSX.Element {
  const { email, setEmail, error, isSubmitting, message, submit } = usePasswordResetRequestForm();

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-center text-2xl font-semibold text-gray-900">Reset your password</h1>

        {error !== null && <ErrorBanner error={error} />}

        {message !== null ? (
          <div
            role="status"
            className="rounded-md border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-800"
          >
            {message}
          </div>
        ) : (
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

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {isSubmitting ? 'Sending…' : 'Send reset link'}
            </button>
          </form>
        )}

        <p className="text-center text-sm text-gray-500">
          <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">
            Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
