import { useCallback, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { login } from '../api/authApi';
import { ApiError } from '../api/problem';
import { useAuthStore } from '../store/authStore';

interface LocationState {
  from?: { pathname: string };
}

const MUST_CHANGE_PASSWORD_SLUG = '/problems/must-change-password';

/** True when the login API error is the must-change-password 403 variant
 * (ADR-0011). Matches on the problem `type` slug, never on `status === 403`
 * alone, since 403 is overloaded with the unrelated deactivated-account
 * case which must keep the existing generic handling. */
export function isMustChangePasswordError(error: unknown): boolean {
  return error instanceof ApiError && error.problem.type.endsWith(MUST_CHANGE_PASSWORD_SLUG);
}

/**
 * Encapsulates the login submit flow: call the API, hydrate the auth store
 * on success, and route to the originally-requested page (or the app
 * root). Kept out of the page component's JSX per the "no inline business
 * logic in JSX" convention.
 */
export function useLoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const setSession = useAuthStore((state) => state.setSession);
  const setUser = useAuthStore((state) => state.setUser);
  const navigate = useNavigate();
  const location = useLocation();

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);
      try {
        const response = await login({ email, password });
        setSession({ accessToken: response.access_token, refreshToken: response.refresh_token });
        setUser(response.user);
        const state = location.state as LocationState | null;
        navigate(state?.from?.pathname ?? '/', { replace: true });
      } catch (err) {
        setError(err);
      } finally {
        setIsSubmitting(false);
      }
    },
    [email, password, location.state, navigate, setSession, setUser],
  );

  return { email, setEmail, password, setPassword, error, isSubmitting, submit };
}
