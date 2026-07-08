import { useCallback, useState } from 'react';
import { changePassword } from '../api/authApi';

/**
 * Encapsulates the authenticated in-app password change flow. On success
 * the current session stays valid (no redirect/logout needed) — every
 * other session is revoked server-side.
 */
export function usePasswordChangeForm() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [succeeded, setSucceeded] = useState(false);

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError(null);
      setSucceeded(false);
      setIsSubmitting(true);
      try {
        await changePassword({ current_password: currentPassword, new_password: newPassword });
        setSucceeded(true);
        setCurrentPassword('');
        setNewPassword('');
      } catch (err) {
        setError(err);
      } finally {
        setIsSubmitting(false);
      }
    },
    [currentPassword, newPassword],
  );

  return {
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    error,
    isSubmitting,
    succeeded,
    submit,
  };
}
