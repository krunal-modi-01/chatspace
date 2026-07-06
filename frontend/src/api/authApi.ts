import { apiRequest } from './httpClient';
import type {
  CurrentUser,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisteredUser,
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
