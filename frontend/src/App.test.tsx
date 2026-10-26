import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'

const admin = {
  id: 'user-1',
  username: 'admin',
  role: 'admin',
  is_active: true,
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(occupancy: unknown = null) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/auth/login'))
      return json({
        access_token: 'test-token',
        token_type: 'bearer',
        expires_in: 900,
      })
    if (url.endsWith('/auth/me')) return json(admin)
    if (url.endsWith('/cameras/current'))
      return json({ id: 'camera-1', name: 'Camera chính', is_active: true })
    if (url.endsWith('/lots/current/occupancy'))
      return json(
        occupancy ?? {
          snapshot_id: null,
          camera_id: 'camera-1',
          captured_at: null,
          as_of: '2026-10-26T00:00:00Z',
          stale_after_seconds: 300,
          counts: null,
          alert_state: 'STALE',
        },
      )
    if (url.includes('/snapshots?'))
      return json({ items: [], page: 1, page_size: 5, total_items: 0 })
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => {
  window.history.replaceState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('redirects an unauthenticated deep link to login', async () => {
  window.history.replaceState({}, '', '/history')
  mockApi()
  render(<App />)
  expect(
    await screen.findByRole('heading', { name: 'Đăng nhập' }),
  ).toBeInTheDocument()
  expect(window.location.pathname).toBe('/login')
})

test('logs in through the existing API and renders honest empty occupancy', async () => {
  const fetchMock = mockApi()
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
  await user.type(screen.getByLabelText('Mật khẩu'), 'correct-password')
  await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

  expect(
    await screen.findByRole('heading', { name: 'Tổng quan' }),
  ).toBeInTheDocument()
  expect(await screen.findByText('Chưa có ảnh chụp')).toBeInTheDocument()
  expect(screen.queryByText('0%', { exact: true })).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/v1/auth/login',
    expect.objectContaining({ method: 'POST' }),
  )
  const meCall = fetchMock.mock.calls.find(([input]) =>
    String(input).endsWith('/auth/me'),
  ) as [RequestInfo | URL, RequestInit?] | undefined
  expect(new Headers(meCall?.[1]?.headers).get('Authorization')).toBe(
    'Bearer test-token',
  )
  await user.click(screen.getByRole('link', { name: 'Lịch sử' }))
  expect(
    await screen.findByRole('heading', { name: 'Lịch sử ảnh chụp' }),
  ).toBeInTheDocument()
})

test('expires the session when a protected API returns 401', async () => {
  let signedIn = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        signedIn = true
        return json({
          access_token: 'expired-token',
          token_type: 'bearer',
          expires_in: 900,
        })
      }
      if (url.endsWith('/auth/me') && signedIn) return json(admin)
      if (url.endsWith('/lots/current/occupancy'))
        return json(
          {
            error: { code: 'UNAUTHENTICATED', message: 'Invalid credentials' },
          },
          401,
        )
      if (url.endsWith('/cameras/current'))
        return json({ id: 'camera-1', name: 'Camera chính' })
      if (url.includes('/snapshots?'))
        return json({ items: [], page: 1, page_size: 5, total_items: 0 })
      throw new Error(`Unexpected request: ${url}`)
    }),
  )
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
  await user.type(screen.getByLabelText('Mật khẩu'), 'correct-password')
  await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))
  await waitFor(() => expect(window.location.pathname).toBe('/login'))
  expect(
    screen.getByText('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'),
  ).toBeInTheDocument()
})
