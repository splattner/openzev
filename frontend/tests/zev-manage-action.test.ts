import { describe, it, expect, vi } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { ToastProvider } from '../src/lib/toast'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ZevListPage } from '../src/pages/ZevListPage'
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
vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => ({ selectedZevId: '', setSelectedZevId: mockSetSelectedZevId }),
}))

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
    createZevWithOwner: vi.fn(),
    updateZev: vi.fn(),
    deleteZev: vi.fn(),
}))

vi.mock('../src/lib/api/auth', () => ({
    fetchUsers: () => Promise.resolve([]),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (d: string) => d,
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

describe('ZevListPage Manage action', () => {
    it('enters ZEV scope (select + go to /) from platform scope', async () => {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        await act(async () => {
            root.render(
                createElement(
                    MemoryRouter,
                    null,
                    createElement(
                        MantineProvider,
                        null,
                        createElement(
                            ToastProvider,
                            null,
                            createElement(
                                QueryClientProvider,
                                { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
                                createElement(ZevListPage),
                            ),
                        ),
                    ),
                ),
            )
        })
        await act(async () => {
            await new Promise((r) => setTimeout(r, 0))
        })
        const button = Array.from(container.querySelectorAll('button')).find((b) =>
            b.textContent?.includes('pages.zevs.manage'),
        )
        expect(button).not.toBe(undefined)
        await act(async () => {
            ;(button as HTMLButtonElement).click()
        })
        expect(mockSetSelectedZevId).toHaveBeenCalledWith('z1')
        expect(mockNavigate).toHaveBeenCalledWith('/')
        act(() => root.unmount())
        container.remove()
    })
})
