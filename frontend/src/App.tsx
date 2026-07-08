import type { JSX } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AdminRoute } from './components/AdminRoute';
import { AppShell } from './components/AppShell';
import { ProtectedRoute } from './components/ProtectedRoute';
import { PublicOnlyRoute } from './components/PublicOnlyRoute';
import { useSessionBootstrap } from './hooks/useSessionBootstrap';
import { InvitesPage } from './pages/admin/InvitesPage';
import { UsersPage } from './pages/admin/UsersPage';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage } from './pages/LoginPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { PasswordChangePage } from './pages/PasswordChangePage';
import { PasswordResetConfirmPage } from './pages/PasswordResetConfirmPage';
import { PasswordResetRequestPage } from './pages/PasswordResetRequestPage';
import { RegisterPage } from './pages/RegisterPage';
import { SessionsPage } from './pages/SessionsPage';

/** Route shell: public auth routes vs. the protected app shell. Feature
 * screens are added under the protected branch in T30+. */
export function App(): JSX.Element {
  useSessionBootstrap();

  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/password-reset" element={<PasswordResetRequestPage />} />
        <Route path="/password-reset/confirm" element={<PasswordResetConfirmPage />} />
      </Route>

      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/settings/password" element={<PasswordChangePage />} />
          <Route path="/settings/sessions" element={<SessionsPage />} />

          <Route element={<AdminRoute />}>
            <Route path="/admin/invites" element={<InvitesPage />} />
            <Route path="/admin/users" element={<UsersPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="/404" element={<NotFoundPage />} />
      <Route path="*" element={<Navigate to="/404" replace />} />
    </Routes>
  );
}
