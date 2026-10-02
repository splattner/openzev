import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { AxiosError } from 'axios'
import type { ZevAccessGrant } from '../src/types/api'

// ZEV settings → Access (#761, SPEC-2026-10-zev-access-grants §9.6).

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, values?: Record<string, string>) => (values?.name ? `${key}:${values.name}` : key) }),
}))
const pushToast = vi.fn()
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast }) }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1 }, refreshUser: vi.fn() }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/appSettings')>()),
    useAppSettings: () => ({ settings: undefined }),
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchZevAccess: vi.fn(),
    createZevAccess: vi.fn(),
    updateZevAccess: vi.fn(),
    revokeZevAccess: vi.fn(),
    resendZevInvitation: vi.fn(),
}))

import { createZevAccess, fetchZevAccess, revokeZevAccess, updateZevAccess } from '../src/lib/api/zev'
import { ZevAccessSection } from '../src/features/zev/ZevAccessSection'

const grant = (over: Partial<ZevAccessGrant> & { email?: string; pending?: boolean } = {}): ZevAccessGrant => ({
    id: over.id ?? 'g1',
    zev: 'z1',
    role: over.role ?? 'manager',
    valid_from: '2026-01-01',
    valid_to: over.valid_to ?? null,
    is_active: true,
    granted_by: null,
    created_at: '2026-01-01T00:00:00Z',
    user: { id: 2, email: over.email ?? 'ann@example.com', first_name: 'Ann', last_name: 'Manager', pending_invitation: over.pending ?? false },
})

const cleanups: (() => void)[] = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchZevAccess).mockResolvedValue([grant(), grant({ id: 'g2', role: 'viewer', email: 'vic@example.com', pending: true })])
})

async function render(canManage: boolean) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => root.render(
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevAccessSection, { zevId: 'z1', canManage }))),
    ))
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    return container
}

const buttons = (container: Element, label: string) =>
    Array.from(container.querySelectorAll('button')).filter((button) => button.textContent?.includes(label))

describe('ZevAccessSection', () => {
    it('lists who has access, with role and a pending invitation', async () => {
        const container = await render(true)
        expect(container.textContent).toContain('ann@example.com')
        expect(container.textContent).toContain('vic@example.com')
        expect(container.textContent).toContain('pages.zevSettings.access.pending')
    })

    it('offers a viewer no actions', async () => {
        const container = await render(false)
        expect(container.textContent).toContain('ann@example.com')
        expect(buttons(container, 'pages.zevSettings.access.add')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.access.revoke')).toHaveLength(0)
        expect(buttons(container, 'pages.zevSettings.access.makeViewer')).toHaveLength(0)
    })

    it('lets a manager give access by email', async () => {
        vi.mocked(createZevAccess).mockResolvedValue({ ...grant({ id: 'g3', role: 'viewer', pending: true }), email_sent: true })
        const container = await render(true)
        await act(async () => buttons(container, 'pages.zevSettings.access.add')[0].click())
        const input = container.querySelector<HTMLInputElement>('input[type="email"]')!
        await act(async () => {
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
            setter.call(input, 'new@example.com')
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
        await act(async () => container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))
        expect(createZevAccess).toHaveBeenCalledWith('z1', { email: 'new@example.com', role: 'viewer', valid_to: null })
        expect(pushToast).toHaveBeenCalledWith('pages.zevSettings.access.invited', 'success')
    })

    it('makes a viewer a manager straight away and asks before making a manager a viewer', async () => {
        vi.mocked(updateZevAccess).mockResolvedValue(grant())
        const container = await render(true)
        await act(async () => buttons(container, 'pages.zevSettings.access.makeManager')[0].click())
        expect(updateZevAccess).toHaveBeenCalledWith('z1', 'g2', { role: 'manager' })
        await act(async () => buttons(container, 'pages.zevSettings.access.makeViewer')[0].click())
        expect(container.textContent).toContain('pages.zevSettings.access.downgradeTitle')
    })

    it('shows the server’s refusal when the last manager would be removed', async () => {
        vi.mocked(revokeZevAccess).mockRejectedValue(new AxiosError('Bad Request', '400', undefined, undefined, {
            status: 400, statusText: 'Bad Request', headers: {}, config: {} as never,
            data: { detail: 'A ZEV needs at least one manager.' },
        }))
        const container = await render(true)
        await act(async () => buttons(container, 'pages.zevSettings.access.revoke')[0].click())
        const confirm = Array.from(document.querySelectorAll('button')).filter((button) => button.textContent === 'pages.zevSettings.access.revoke').pop()!
        await act(async () => confirm.click())
        await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
        expect(pushToast).toHaveBeenCalledWith(expect.stringContaining('A ZEV needs at least one manager.'), 'error')
    })
})
