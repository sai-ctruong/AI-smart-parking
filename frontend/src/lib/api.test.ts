import { afterEach, expect, test, vi } from 'vitest'
import { apiRequest } from './api'

afterEach(() => vi.unstubAllGlobals())

test('accepts an authorized delete with an empty 204 response', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(null, { status: 204 })),
  )
  await expect(
    apiRequest<void>('/spots/spot-1', 'token', () => {}, { method: 'DELETE' }),
  ).resolves.toBeUndefined()
})
