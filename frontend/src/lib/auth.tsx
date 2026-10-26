import { useQueryClient } from '@tanstack/react-query'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { apiBlob, apiRequest, loginRequest } from './api'
import type { User } from './api'

interface Session {
  token: string
  user: User
  expiresAt: number
}

interface AuthValue {
  session: Session | null
  notice: string | null
  login: (username: string, password: string) => Promise<void>
  logout: (expired?: boolean) => void
  request: <T>(path: string, options?: RequestInit) => Promise<T>
  blob: (path: string) => Promise<Blob>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const logout = useCallback(
    (expired = false) => {
      setSession(null)
      setNotice(
        expired ? 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.' : null,
      )
      queryClient.clear()
    },
    [queryClient],
  )

  useEffect(() => {
    if (!session) return
    const timer = window.setTimeout(
      () => logout(true),
      Math.max(0, session.expiresAt - Date.now()),
    )
    return () => window.clearTimeout(timer)
  }, [session, logout])

  const login = useCallback(
    async (username: string, password: string) => {
      const response = await loginRequest(username, password)
      const user = await apiRequest<User>(
        '/auth/me',
        response.access_token,
        () => logout(true),
      )
      setNotice(null)
      setSession({
        token: response.access_token,
        user,
        expiresAt: Date.now() + response.expires_in * 1000,
      })
    },
    [logout],
  )

  const request = useCallback(
    <T,>(path: string, options?: RequestInit) => {
      if (!session) return Promise.reject(new Error('Chưa đăng nhập'))
      return apiRequest<T>(path, session.token, () => logout(true), options)
    },
    [session, logout],
  )

  const blob = useCallback(
    async (path: string) => {
      if (!session) throw new Error('Chưa đăng nhập')
      return apiBlob(path, session.token, () => logout(true))
    },
    [session, logout],
  )

  const value = useMemo(
    () => ({ session, notice, login, logout, request, blob }),
    [session, notice, login, logout, request, blob],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is missing')
  return value
}
