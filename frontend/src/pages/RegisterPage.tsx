import type { JSX } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '../components/ErrorBanner';
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
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center px-4"
      >
        <span className="text-sm text-gray-500">Checking your invite…</span>
      </div>
    );
  }

  if (inviteStatus === 'invalid') {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-4 text-center">
          <h1 className="text-2xl font-semibold text-gray-900">Invite link no longer valid</h1>
          <p className="text-sm text-gray-600">This invite link is no longer valid.</p>
          {inviteError !== null && <ErrorBanner error={inviteError} />}
          <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm space-y-6">
        <h1 className="text-center text-2xl font-semibold text-gray-900">Create your account</h1>

        {submitError !== null && <ErrorBanner error={submitError} />}

        <form className="space-y-4" onSubmit={submit} noValidate>
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700">
              Email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              readOnly
              disabled
              value={inviteEmail ?? ''}
              className="mt-1 block w-full rounded-md border border-gray-300 bg-gray-100 px-3 py-2 text-sm text-gray-600"
            />
          </div>

          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700">
              Username
            </label>
            <input
              id="username"
              name="username"
              type="text"
              autoComplete="username"
              required
              minLength={1}
              maxLength={32}
              value={fields.username}
              onChange={(event) => setField('username', event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="firstName" className="block text-sm font-medium text-gray-700">
                First name
              </label>
              <input
                id="firstName"
                name="firstName"
                type="text"
                autoComplete="given-name"
                required
                value={fields.firstName}
                onChange={(event) => setField('firstName', event.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label htmlFor="lastName" className="block text-sm font-medium text-gray-700">
                Last name
              </label>
              <input
                id="lastName"
                name="lastName"
                type="text"
                autoComplete="family-name"
                required
                value={fields.lastName}
                onChange={(event) => setField('lastName', event.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={6}
              value={fields.password}
              onChange={(event) => setField('password', event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              aria-describedby="password-hint"
            />
            <p id="password-hint" className="mt-1 text-xs text-gray-500">
              At least 6 characters, with at least one letter and one digit.
            </p>
          </div>

          <div>
            <label htmlFor="avatarUrl" className="block text-sm font-medium text-gray-700">
              Avatar URL <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <input
              id="avatarUrl"
              name="avatarUrl"
              type="url"
              value={fields.avatarUrl}
              onChange={(event) => setField('avatarUrl', event.target.value)}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isSubmitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>

        <p className="text-center text-sm text-gray-500">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-indigo-600 hover:text-indigo-500">
            Sign in
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
