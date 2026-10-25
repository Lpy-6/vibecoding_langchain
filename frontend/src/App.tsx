import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { Spin } from 'antd'
import { useAuthStore } from './stores/auth'
import LoginPage from './pages/LoginPage'
import ChatPage from './pages/ChatPage'
import ProfilePage from './pages/ProfilePage'

const AdminLayout = lazy(() => import('./pages/admin/AdminLayout'))
const KbListPage = lazy(() => import('./pages/admin/KbListPage'))
const KbDetailPage = lazy(() => import('./pages/admin/KbDetailPage'))
const UsersPage = lazy(() => import('./pages/admin/UsersPage'))
const StatsPage = lazy(() => import('./pages/admin/StatsPage'))
const FeedbackPage = lazy(() => import('./pages/admin/FeedbackPage'))
const AuditPage = lazy(() => import('./pages/admin/AuditPage'))

function RequireAuth() {
  const user = useAuthStore((s) => s.user)
  return user ? <Outlet /> : <Navigate to="/login" replace />
}

function RequireAdmin() {
  const user = useAuthStore((s) => s.user)
  return user?.role === 'admin' ? <Outlet /> : <Navigate to="/" replace />
}

export default function App() {
  const bootstrapped = useAuthStore((s) => s.bootstrapped)
  const bootstrap = useAuthStore((s) => s.bootstrap)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  if (!bootstrapped) {
    return (
      <div className="app-loading">
        <Spin size="large" />
        <div style={{ marginTop: 16, color: '#64748b' }}>正在恢复登录状态…</div>
      </div>
    )
  }

  return (
    <Suspense
      fallback={
        <div className="app-loading">
          <Spin size="large" />
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<ChatPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route element={<RequireAdmin />}>
            <Route path="/admin" element={<AdminLayout />}>
              <Route index element={<Navigate to="/admin/kbs" replace />} />
              <Route path="kbs" element={<KbListPage />} />
              <Route path="kbs/:kbId" element={<KbDetailPage />} />
              <Route path="users" element={<UsersPage />} />
              <Route path="stats" element={<StatsPage />} />
              <Route path="feedback" element={<FeedbackPage />} />
              <Route path="audit" element={<AuditPage />} />
            </Route>
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}
