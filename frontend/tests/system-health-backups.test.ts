import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AdminSystemHealthPanel } from '../src/pages/AdminSystemHealthPanel'
import type { SystemHealth } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return { ...actual, formatDateTime: (value: string) => `at:${value}` }
})

const fetchSystemHealth = vi.hoisted(() => vi.fn())
vi.mock('../src/lib/api/auth', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/api/auth')>()
    return { ...actual, fetchSystemHealth }
})

const health = (backups: SystemHealth['backups']): SystemHealth => ({
    database: { status: 'ok', engine: 'postgresql', size_bytes: 1024 },
    celery: { status: 'ok', workers_responding: 1, queue_depth: 0, broker_configured: true },
    mfa: { status: 'ok', encryption_key_configured: true },
    email: { status: 'ok', mode: 'smtp', backend: 'EmailBackend' },
    backups,
    checked_at: '2026-09-22T10:00:00Z',
})

const cleanups: (() => void)[] = []
beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
        writable: true, configurable: true,
        value: (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false, onchange: null }),
    })
})
afterEach(() => { cleanups.splice(0).forEach((cleanup) => cleanup()); vi.clearAllMocks() })

async function render(backups: SystemHealth['backups']) {
    fetchSystemHealth.mockResolvedValue(health(backups))
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); client.clear(); container.remove() })
    await act(async () => root.render(
        createElement(QueryClientProvider, { client },
            createElement(MantineProvider, null, createElement(MemoryRouter, null, createElement(AdminSystemHealthPanel)))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)) })
    return container
}

const card = (container: Element) =>
    Array.from(container.querySelectorAll('.system-health-probe')).find((c) => c.textContent?.includes('pages.adminOverview.health.backups.title'))!

describe('the backups card on the system health tab', () => {
    it('says backups are not set up when no destination is enabled — a state, not a fault', async () => {
        const c = card(await render({ status: 'unknown' }))
        expect(c.textContent).toContain('pages.adminOverview.health.status.unknown')
        expect(c.textContent).toContain('pages.adminOverview.health.backups.notSetUp')
        expect(c.querySelector('.dot-info')).toBeTruthy()
    })

    it('shows when the last backup finished, and links to where they are managed', async () => {
        const c = card(await render({ status: 'ok', last_successful_at: '2026-09-22T02:00:00Z', stale: false, encrypted: true }))
        expect(c.textContent).toContain('pages.adminOverview.health.backups.last')
        expect(c.querySelector('a')?.getAttribute('href')).toBe('/admin/system-settings?tab=backup')
        expect(c.querySelector('.dot-success')).toBeTruthy()
        expect(c.textContent).not.toContain('pages.adminOverview.health.backups.stale')
    })

    it('goes loudly degraded when the schedule has fallen behind', async () => {
        const c = card(await render({ status: 'degraded', last_successful_at: '2026-09-18T02:00:00Z', stale: true, encrypted: true }))
        expect(c.querySelector('.dot-warning')).toBeTruthy()
        expect(c.textContent).toContain('pages.adminOverview.health.backups.stale')
    })

    it('says so when nothing has ever finished', async () => {
        const c = card(await render({ status: 'degraded', last_successful_at: null, stale: false, encrypted: true }))
        expect(c.textContent).toContain('pages.adminOverview.health.backups.never')
    })

    it('flags unencrypted backups, but not when backups are not set up', async () => {
        expect(card(await render({ status: 'ok', last_successful_at: '2026-09-22T02:00:00Z', encrypted: false })).textContent)
            .toContain('pages.adminOverview.health.backups.unencrypted')
        cleanups.splice(0).forEach((cleanup) => cleanup())
        expect(card(await render({ status: 'unknown', encrypted: false })).textContent)
            .not.toContain('pages.adminOverview.health.backups.unencrypted')
    })
})
