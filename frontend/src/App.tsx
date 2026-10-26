import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from 'react-router'
import { AuthProvider, useAuth } from './lib/auth'
import LoginPage from './pages/LoginPage'
import OverviewPage from './pages/OverviewPage'
import ConfigurationPage from './pages/ConfigurationPage'
import AnalysisPage from './pages/AnalysisPage'
import HistoryPage from './pages/HistoryPage'
import ReviewPage from './pages/ReviewPage'

const links = [
  { to: '/overview', label: 'Tổng quan', symbol: '◫' },
  { to: '/configuration', label: 'Cấu hình bãi đỗ', symbol: '▦' },
  { to: '/analysis', label: 'Phân tích ảnh', symbol: '▧' },
  { to: '/history', label: 'Lịch sử', symbol: '◷' },
  { to: '/review', label: 'Duyệt kết quả', symbol: 'R' },
]

function ProtectedLayout() {
  const { session, logout } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  if (!session)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return (
    <div className="app-frame">
      <a className="skip-link" href="#main-content">
        Bỏ qua điều hướng
      </a>
      <div className="app-sheet">
        <aside
          className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}
          aria-label="Điều hướng chính"
        >
          <Link
            to="/overview"
            className="brand"
            onClick={() => setMenuOpen(false)}
          >
            <span className="parking-mark" aria-hidden="true">
              <span />
              <span />
              <span />
              <span />
            </span>
            <span>
              Smart Parking<small>MANAGEMENT SYSTEM</small>
            </span>
          </Link>
          <div className="sidebar-caption">KHÔNG GIAN LÀM VIỆC</div>
          <nav className="space-y-1" aria-label="Trang chính">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `nav-link ${isActive ? 'nav-link-active' : ''}`
                }
              >
                <span className="nav-symbol" aria-hidden="true">
                  {link.symbol}
                </span>
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-footer">
            <p className="text-xs text-[var(--muted)]">ĐANG ĐĂNG NHẬP</p>
            <p className="mt-2 truncate text-sm font-semibold">
              {session.user.username}
            </p>
            <p className="text-xs text-[var(--muted)]">
              {session.user.role === 'admin' ? 'Admin' : 'Operator'}
            </p>
            <button
              type="button"
              className="text-link mt-4"
              onClick={() => logout()}
            >
              Đăng xuất
            </button>
          </div>
        </aside>
        <div className="content-column">
          <header className="topbar">
            <button
              type="button"
              className="menu-button"
              aria-label="Mở menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              Menu
            </button>
            <span className="text-sm text-[var(--muted)]">
              Smart Parking <span className="mx-2 text-[var(--border)]">/</span>{' '}
              Vận hành
            </span>
            <span className="ml-auto text-xs font-medium text-[var(--muted)]">
              {session.user.role === 'admin' ? 'ADMIN' : 'OPERATOR'}
            </span>
          </header>
          <main id="main-content" className="page-content">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 30_000, retry: false } },
      }),
  )
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/configuration" element={<ConfigurationPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/review" element={<ReviewPage />} />
              <Route path="/review/:snapshotId" element={<ReviewPage />} />
              <Route path="/" element={<Navigate to="/overview" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
