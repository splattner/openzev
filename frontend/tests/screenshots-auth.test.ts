// @vitest-environment node
import { describe, expect, it, vi } from 'vitest'
import type { Page } from '@playwright/test'

// Helpers use Playwright assertions; keep these request-level regressions in
// the unit suite without invoking the screenshot runner or a demo server.
vi.mock('@playwright/test', async () => ({ expect: (await import('vitest')).expect }))

import { API_BASE, getAdminToken } from '../screenshots/helpers'

function mockPage(cookieValues: Array<string | undefined>, status = 200) {
  const cookies = vi.fn()
  for (const value of cookieValues) {
    cookies.mockResolvedValueOnce(value ? [{ name: 'openzev_access', value }] : [])
  }
  const post = vi.fn().mockResolvedValue({ ok: () => status === 200, status: () => status })
  const page = {
    context: () => ({ cookies }),
    request: { post },
  } as unknown as Page
  return { page, cookies, post }
}

describe('screenshot authentication', () => {
  it('reuses the saved API cookie without spending another login', async () => {
    const { page, cookies, post } = mockPage(['saved-access'])
    await expect(getAdminToken(page)).resolves.toBe('saved-access')
    expect(cookies).toHaveBeenCalledWith(API_BASE)
    expect(post).not.toHaveBeenCalled()
  })

  it('logs in exactly once when the context has no API access cookie', async () => {
    const { page, post } = mockPage([undefined, 'new-access'])
    await expect(getAdminToken(page)).resolves.toBe('new-access')
    expect(post).toHaveBeenCalledExactlyOnceWith(`${API_BASE}/auth/token/`, {
      data: { username: expect.any(String), password: expect.any(String) },
    })
  })

  it('reports a throttled login without retrying it', async () => {
    const { page, post } = mockPage([undefined], 429)
    await expect(getAdminToken(page)).rejects.toThrow('Admin login failed (429)')
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('fails if a successful login does not set the access cookie', async () => {
    const { page, post } = mockPage([undefined, undefined])
    await expect(getAdminToken(page)).rejects.toThrow('openzev_access cookie missing after login')
    expect(post).toHaveBeenCalledTimes(1)
  })
})
