import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function LoginPage() {
  const { session, login, notice } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (session) return <Navigate to="/overview" replace />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(username, password)
      const destination =
        (location.state as { from?: string } | null)?.from || '/overview'
      navigate(destination, { replace: true })
    } catch (cause) {
      setError(
        cause instanceof ApiError && cause.status === 401
          ? 'Tên đăng nhập hoặc mật khẩu không đúng.'
          : 'Không thể đăng nhập. Kiểm tra kết nối API rồi thử lại.',
      )
    } finally {
      setPending(false)
    }
  }

  return (
    <main className="login-screen grid min-h-screen lg:grid-cols-[1fr_1fr]">
      <div className="flex min-h-[240px] flex-col justify-between bg-[var(--ground)] p-6 sm:p-10 lg:p-14">
        <div className="flex items-center gap-3">
          <span className="parking-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span className="text-lg font-semibold">Smart Parking</span>
        </div>
        <div className="max-w-lg py-8 lg:py-0">
          <p className="text-sm font-medium text-[var(--accent)]">
            Không gian vận hành
          </p>
          <h2 className="mt-4 max-w-md text-3xl font-medium leading-tight tracking-tight sm:text-4xl">
            Một góc nhìn rõ ràng cho từng chỗ đỗ.
          </h2>
          <p className="mt-5 max-w-md text-base leading-7 text-[var(--muted)]">
            Theo dõi camera cố định, phân tích ảnh chụp và xác nhận kết quả
            trong cùng một hệ thống.
          </p>
        </div>
        <p className="text-xs text-[var(--muted)]">
          Smart Parking Management System
        </p>
      </div>
      <div className="flex items-center justify-center bg-white px-6 py-12 sm:px-10">
        <form className="w-full max-w-sm" onSubmit={submit}>
          <h1 className="text-[28px] font-semibold tracking-tight">
            Đăng nhập
          </h1>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Sử dụng tài khoản Admin hoặc Operator đã được cấp.
          </p>
          {notice && (
            <p
              role="status"
              className="mt-6 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900"
            >
              {notice}
            </p>
          )}
          {error && (
            <p
              role="alert"
              className="mt-6 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-900"
            >
              {error}
            </p>
          )}
          <div className="mt-8 space-y-5">
            <label className="block text-sm font-medium" htmlFor="username">
              Tên đăng nhập
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              spellCheck={false}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="input -mt-3 block w-full"
            />
            <label className="block text-sm font-medium" htmlFor="password">
              Mật khẩu
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="input -mt-3 block w-full"
            />
          </div>
          <button
            type="submit"
            disabled={pending}
            className="primary-button mt-8 w-full"
          >
            {pending ? 'Đang đăng nhập…' : 'Đăng nhập'}
          </button>
          <p className="mt-6 text-xs leading-5 text-[var(--muted)]">
            Phiên làm việc chỉ được giữ trong bộ nhớ trình duyệt. Đăng nhập lại
            sau khi tải lại trang.
          </p>
        </form>
      </div>
    </main>
  )
}
