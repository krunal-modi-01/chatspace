import { apiRequest } from './httpClient';
import type {
  CurrentUser,
  InviteTokenValidation,
  LoginRequest,
  LoginResponse,
  PasswordChangeRequest,
  PasswordResetAcceptedResponse,
  PasswordResetConfirmRequest,
  PasswordResetRequest,
  RegisterRequest,
  RegisteredUser,
  SessionListResponse,
} from './types';

/** Public — no Bearer token sent or required. */
export function login(payload: LoginRequest): Promise<LoginResponse> {
  return apiRequest<LoginResponse>('/auth/login', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

/** Public — invite-gated registration. */
export function register(payload: RegisterRequest): Promise<RegisteredUser> {
  return apiRequest<RegisteredUser>('/auth/register', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

/** Protected — idempotent logout of the current session. */
export function logout(): Promise<void> {
  return apiRequest<void>('/auth/logout', {
    method: 'POST',
    body: {},
  });
}

/** Protected — populates the current-user store. */
export function fetchCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/me', { method: 'GET' });
}

/** Public — pre-fills and locks the registration email for an invite token.
 * The raw token comes from the URL query string; the server hashes it to
 * look the invite up. */
export function fetchInvite(token: string): Promise<InviteTokenValidation> {
  return apiRequest<InviteTokenValidation>(`/invites/${encodeURIComponent(token)}`, {
    method: 'GET',
    auth: false,
  });
}

/** Public — always returns the uniform 202 message regardless of whether
 * the email matches an account (non-enumerating, F15). */
export function requestPasswordReset(payload: PasswordResetRequest): Promise<PasswordResetAcceptedResponse> {
  return apiRequest<PasswordResetAcceptedResponse>('/auth/password-reset', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

/** Public — the raw reset token from the URL is the credential; 204 on
 * success (all other sessions are invalidated server-side). */
export function confirmPasswordReset(payload: PasswordResetConfirmRequest): Promise<void> {
  return apiRequest<void>('/auth/password-reset/confirm', {
    method: 'POST',
    body: payload,
    auth: false,
  });
}

/** Protected — the current session stays valid; every other session is
 * revoked server-side. */
export function changePassword(payload: PasswordChangeRequest): Promise<void> {
  return apiRequest<void>('/auth/password/change', {
    method: 'POST',
    body: payload,
  });
}

/** Protected — lists the caller's own active sessions. */
export function listSessions(): Promise<SessionListResponse> {
  return apiRequest<SessionListResponse>('/auth/sessions', { method: 'GET' });
}

/** Protected, own-only — idempotent revoke of a specific session. */
export function revokeSession(sessionId: string): Promise<void> {
  return apiRequest<void>(`/auth/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  });
}
