import { useCallback, useState } from 'react';
import { requestPasswordReset } from '../api/authApi';

/**
 * Encapsulates the "request a password reset" flow. The backend response is
 * uniform (202, same message) whether or not the email matches an account
 * (non-enumeration, F15) — the UI shows that message verbatim on success.
 */
export function usePasswordResetRequestForm() {
  const [email, setEmail] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);
      try {
        const response = await requestPasswordReset({ email });
        setMessage(response.message);
      } catch (err) {
        setError(err);
      } finally {
        setIsSubmitting(false);
      }
    },
    [email],
  );

  return { email, setEmail, error, isSubmitting, message, submit };
}
