import { afterEach, describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { ToastProvider } from '../src/lib/toast'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ZevListPage } from '../src/pages/ZevListPage'
import { updateZev } from '../src/lib/api/zev'
import type { Zev } from '../src/types/api'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (k: string) => k,
        i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({
        user: { id: 1, username: 'admin', email: 'a@x.ch', first_name: '', last_name: '', role: 'admin' },
    }),
}))

const mockSetSelectedZevId = vi.fn()
vi.mock('../src/lib/managedZev', () => {
    const context = {
        useManagedZev: () => ({ selectedZevId: '', setSelectedZevId: mockSetSelectedZevId }),
    }
    return { ...context, useOptionalManagedZev: context.useManagedZev }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router-dom')>()),
    useNavigate: () => mockNavigate,
}))

const ZEV = {
    id: 'z1',
    name: 'Muster ZEV',
    start_date: '2026-01-01',
    owner: 9,
    zev_type: 'zev',
    grid_operator: '',
    billing_interval: 'monthly',
} as Zev

vi.mock('../src/lib/api/zev', () => ({
    fetchZevs: () => Promise.resolve([ZEV]),
    fetchParticipants: () => Promise.resolve([]),
    fetchGridOperators: () => Promise.resolve({ operators: [], source: '', cube: '', licence: '', period: '', fetched_on: '' }),
    createZevWithOwner: vi.fn(),
    updateZev: vi.fn(),
    disableZev: vi.fn(),
    enableZev: vi.fn(),
    purgeZev: vi.fn(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: () => Promise.resolve([]),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
    toDayJsDateFormat: () => 'DD.MM.YYYY',
}))

vi.mock('../src/components/ConfirmDialog', () => ({
    ConfirmDialog: () => null,
    useConfirmDialog: () => ({
        dialog: null,
        confirm: vi.fn(),
        handleConfirm: vi.fn(),
        handleCancel: vi.fn(),
        isLoading: false,
    }),
}))

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

async function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    await act(async () => {
        root.render(createElement(MemoryRouter, null, createElement(MantineProvider, null, createElement(ToastProvider, null,
            createElement(QueryClientProvider, { client }, createElement(ZevListPage))))))
    })
    const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)) })
    await vi.waitFor(async () => {
        await flush()
        expect(container.querySelector('tbody tr')).not.toBeNull()
    })
    return { container, client, flush }
}

describe('ZevListPage Manage action', () => {
    it('enters ZEV scope (select + go to /) from platform scope', async () => {
        const { container } = await mount()
        const button = Array.from(container.querySelectorAll('button')).find((b) =>
            b.textContent?.includes('pages.zevs.manage'),
        )
        expect(button).not.toBe(undefined)
        await act(async () => {
            ;(button as HTMLButtonElement).click()
        })
        expect(mockSetSelectedZevId).toHaveBeenCalledWith('z1')
        expect(mockNavigate).toHaveBeenCalledWith('/')
    })

    it('invalidates billing readiness for the edited community', async () => {
        vi.mocked(updateZev).mockResolvedValue(ZEV)
        const { container, client, flush } = await mount()
        const invalidate = vi.spyOn(client, 'invalidateQueries')
        await act(async () => { container.querySelector<HTMLButtonElement>('button[aria-label="common.editNamed"]')!.click() })
        const dialog = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'))
            .find((d) => d.textContent?.includes('pages.zevs.editModalTitle'))!
        const save = Array.from(dialog.querySelectorAll<HTMLButtonElement>('button[type="submit"]'))
            .find((b) => b.textContent?.includes('pages.zevs.saveZev'))!
        await act(async () => { save.click() })
        expect(updateZev).toHaveBeenCalledWith('z1', expect.any(Object))
        const keys = () => invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
        await vi.waitFor(async () => {
            await flush()
            for (const expected of [['zev', 'list'], ['invoices', 'readiness', 'z1'], ['invoices', 'readiness-list', 'z1']]) {
                expect(keys(), expected.join('/')).toContain(JSON.stringify(expected))
            }
        })
    })
})
