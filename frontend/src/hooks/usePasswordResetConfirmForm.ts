import { useCallback, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { confirmPasswordReset } from '../api/authApi';
import { ApiError } from '../api/problem';

/**
 * Drives the "set a new password" step: reads the raw reset token from the
 * URL query string (same pattern as the invite flow) and submits it with
 * the new password to `POST /v1/auth/password-reset/confirm`.
 */
export function usePasswordResetConfirmForm() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTokenStale, setIsTokenStale] = useState(token === '');
  const navigate = useNavigate();

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);
      try {
        await confirmPasswordReset({ reset_token: token, new_password: newPassword });
        navigate('/login', { replace: true });
      } catch (err) {
        if (err instanceof ApiError && err.status === 410) {
          setIsTokenStale(true);
        }
        setError(err);
      } finally {
        setIsSubmitting(false);
      }
    },
    [navigate, newPassword, token],
  );

  return { newPassword, setNewPassword, error, isSubmitting, isTokenStale, submit };
}
