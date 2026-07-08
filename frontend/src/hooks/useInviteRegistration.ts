import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { fetchInvite, register } from '../api/authApi';
import { ApiError } from '../api/problem';
import type { RegisterRequest } from '../api/types';

type InviteStatus = 'loading' | 'valid' | 'invalid';

interface RegistrationFields {
  username: string;
  firstName: string;
  lastName: string;
  password: string;
  avatarUrl: string;
}

const INITIAL_FIELDS: RegistrationFields = {
  username: '',
  firstName: '',
  lastName: '',
  password: '',
  avatarUrl: '',
};

/**
 * Drives the invite-redemption registration flow: reads the invite token
 * from the URL, prefetches (and locks) the invited email via
 * `GET /v1/invites/{token}`, then submits the registration form against
 * `POST /v1/auth/register`. Kept out of the page component's JSX per the
 * "no inline business logic in JSX" convention.
 */
export function useInviteRegistration() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [inviteStatus, setInviteStatus] = useState<InviteStatus>('loading');
  const [inviteEmail, setInviteEmail] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<unknown>(null);

  const [fields, setFields] = useState<RegistrationFields>(INITIAL_FIELDS);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;

    if (!token) {
      setInviteStatus('invalid');
      return;
    }

    setInviteStatus('loading');
    fetchInvite(token)
      .then((invite) => {
        if (cancelled) return;
        setInviteEmail(invite.email);
        setInviteStatus('valid');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setInviteError(err);
        setInviteStatus('invalid');
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const setField = useCallback(
    <K extends keyof RegistrationFields>(key: K, value: RegistrationFields[K]) => {
      setFields((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const submit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setSubmitError(null);
      setIsSubmitting(true);
      try {
        const payload: RegisterRequest = {
          invite_token: token,
          username: fields.username,
          first_name: fields.firstName,
          last_name: fields.lastName,
          password: fields.password,
          avatar_url: fields.avatarUrl.trim() === '' ? null : fields.avatarUrl,
        };
        await register(payload);
        navigate('/login', { replace: true });
      } catch (err) {
        if (err instanceof ApiError && err.status === 410) {
          // Invite went stale between prefill and submit — reflect that in
          // the gating state, not just the submit error banner.
          setInviteStatus('invalid');
          setInviteError(err);
        }
        setSubmitError(err);
      } finally {
        setIsSubmitting(false);
      }
    },
    [fields, navigate, token],
  );

  return {
    inviteStatus,
    inviteEmail,
    inviteError,
    fields,
    setField,
    submitError,
    isSubmitting,
    submit,
  };
}
