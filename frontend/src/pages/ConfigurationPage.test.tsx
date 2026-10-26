import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

test('Admin uploads the camera reference and opens its polygon workspace', async () => {
  window.history.replaceState({}, '', '/configuration')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login'))
        return json({
          access_token: 'admin-token',
          token_type: 'bearer',
          expires_in: 900,
        })
      if (url.endsWith('/auth/me'))
        return json({
          id: 'admin-1',
          username: 'admin',
          role: 'admin',
          is_active: true,
        })
      if (url.endsWith('/cameras/current'))
        return json({
          id: 'camera-1',
          name: 'Camera chính',
          is_active: true,
          viewpoint_version: 1,
          reference_image: { sha256: 'a'.repeat(64), width: 1200, height: 800 },
        })
      if (url.endsWith('/cameras/camera-1/spots')) return json({ items: [] })
      if (
        url.endsWith('/cameras/camera-1/reference-image') &&
        options?.method === 'PUT'
      )
        return json({ sha256: 'a'.repeat(64), width: 1200, height: 800 })
      if (url.endsWith('/cameras/camera-1/reference-image'))
        return json(
          { error: { code: 'NOT_FOUND', message: 'Image missing' } },
          404,
        )
      throw new Error(`Unexpected request: ${url}`)
    }),
  )
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
  await user.type(screen.getByLabelText('Mật khẩu'), 'password')
  await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))
  await user.click(await screen.findByRole('link', { name: 'Cấu hình bãi đỗ' }))
  expect(
    await screen.findByText('Ảnh tham chiếu chưa được tải lên'),
  ).toBeInTheDocument()
  const file = new File(['image-bytes'], 'reference.png', { type: 'image/png' })
  await user.upload(screen.getByLabelText('Tải ảnh tham chiếu'), file)
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/cameras/camera-1/reference-image',
      expect.objectContaining({ method: 'PUT', body: expect.any(FormData) }),
    ),
  )
})
