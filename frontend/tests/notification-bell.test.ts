import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options?.count !== undefined ? `${key}:${options.count}` : key) }),
}))

vi.mock('../src/lib/appSettings', async () => {
    const actual = await vi.importActual<typeof import('../src/lib/appSettings')>('../src/lib/appSettings')
    return { ...actual, useOptionalAppSettings: () => actual.DEFAULT_APP_SETTINGS }
})

vi.mock('../src/lib/api/notifications', () => ({
    fetchNotifications: vi.fn(),
    fetchUnreadNotificationCount: vi.fn(),
    markNotificationRead: vi.fn(() => Promise.resolve({})),
    markAllNotificationsRead: vi.fn(() => Promise.resolve(0)),
}))

import { NotificationBell } from '../src/components/NotificationBell'
import * as api from '../src/lib/api/notifications'
import type { Notification } from '../src/types/api'
import { waitForCondition } from './helpers/waitForCondition'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function note(overrides: Partial<Notification> = {}): Notification {
    return {
        id: 'n1', type: 'import.failed', audience: 'manager', zev: 'z1', zev_name: 'ZEV One',
        payload: { rows_skipped: 3, issues: 1 }, target_type: 'import_log', target_id: 'log-1',
        created_at: '2026-03-01T10:00:00Z', read_at: null, ...overrides,
    }
}

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

function Location() {
    return createElement('output', { 'data-testid': 'location' }, useLocation().pathname)
}

async function mount() {
    await act(async () => root.render(
        createElement(QueryClientProvider, { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
            createElement(MemoryRouter, { initialEntries: ['/start'] },
                createElement(NotificationBell),
                createElement(Routes, null, createElement(Route, { path: '*', element: createElement(Location) })))),
    ))
}

const trigger = () => container.querySelector<HTMLButtonElement>('.notification-bell-trigger')!

beforeEach(() => {
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
    vi.mocked(api.fetchNotifications).mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    vi.mocked(api.fetchUnreadNotificationCount).mockResolvedValue(0)
})

afterEach(() => {
    act(() => root.unmount())
    container.remove()
    vi.clearAllMocks()
})

describe('NotificationBell', () => {
    it('shows the unread count on the bell and names it for assistive technology', async () => {
        vi.mocked(api.fetchUnreadNotificationCount).mockResolvedValue(3)
        await mount()
        await waitForCondition(() => container.querySelector('.notification-bell-badge') !== null, 'badge')
        expect(container.querySelector('.notification-bell-badge')!.textContent).toBe('3')
        expect(trigger().getAttribute('aria-label')).toBe('notifications.triggerUnread:3')
    })

    it('shows no badge when everything is read', async () => {
        await mount()
        await act(async () => { await Promise.resolve() })
        expect(container.querySelector('.notification-bell-badge')).toBeNull()
        expect(trigger().getAttribute('aria-label')).toBe('notifications.trigger')
    })

    it('opens a panel with an empty state', async () => {
        await mount()
        await act(async () => trigger().click())
        await waitForCondition(() => container.querySelector('.notification-panel-empty')?.textContent === 'notifications.empty', 'empty state')
        expect(container.querySelector('.notification-panel-empty')!.textContent).toBe('notifications.empty')
    })

    it('marks a notification read and goes to its target when it is opened', async () => {
        vi.mocked(api.fetchUnreadNotificationCount).mockResolvedValue(1)
        vi.mocked(api.fetchNotifications).mockResolvedValue({ count: 1, next: null, previous: null, results: [note()] })
        await mount()
        await act(async () => trigger().click())
        await waitForCondition(() => container.querySelector('.notification-item') !== null, 'item')
        expect(container.querySelector('.notification-item.is-unread')).not.toBeNull()
        await act(async () => container.querySelector<HTMLButtonElement>('.notification-item')!.click())
        expect(vi.mocked(api.markNotificationRead).mock.calls[0][0]).toBe('n1')
        expect(container.querySelector('[data-testid="location"]')!.textContent).toBe('/metering/imports')
        expect(container.querySelector('.notification-panel')).toBeNull()
    })

    it('does not mark an already read notification again', async () => {
        vi.mocked(api.fetchNotifications).mockResolvedValue({ count: 1, next: null, previous: null, results: [note({ read_at: '2026-03-02T00:00:00Z' })] })
        await mount()
        await act(async () => trigger().click())
        await waitForCondition(() => container.querySelector('.notification-item') !== null, 'item')
        await act(async () => container.querySelector<HTMLButtonElement>('.notification-item')!.click())
        expect(api.markNotificationRead).not.toHaveBeenCalled()
    })

    it('marks all read from the panel header', async () => {
        vi.mocked(api.fetchUnreadNotificationCount).mockResolvedValue(2)
        vi.mocked(api.fetchNotifications).mockResolvedValue({ count: 1, next: null, previous: null, results: [note()] })
        await mount()
        await waitForCondition(() => container.querySelector('.notification-bell-badge') !== null, 'badge')
        await act(async () => trigger().click())
        await waitForCondition(() => container.querySelector('.notification-panel .button') !== null, 'header button')
        await act(async () => container.querySelector<HTMLButtonElement>('.notification-panel .button')!.click())
        expect(api.markAllNotificationsRead).toHaveBeenCalled()
    })

    it('names the community only when the list spans more than one', async () => {
        vi.mocked(api.fetchNotifications).mockResolvedValue({
            count: 2, next: null, previous: null,
            results: [note(), note({ id: 'n2', zev: 'z2', zev_name: 'ZEV Two' })],
        })
        await mount()
        await act(async () => trigger().click())
        await waitForCondition(() => container.querySelectorAll('.notification-item').length === 2, 'items')
        expect(container.textContent).toContain('ZEV Two')
    })

    it('closes on Escape and returns focus to the bell', async () => {
        await mount()
        await act(async () => trigger().click())
        expect(container.querySelector('.notification-panel')).not.toBeNull()
        await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
        expect(container.querySelector('.notification-panel')).toBeNull()
        expect(document.activeElement).toBe(trigger())
    })
})
