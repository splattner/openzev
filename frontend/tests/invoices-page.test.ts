import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, createElement, useLayoutEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'

const state = vi.hoisted(() => ({ scope: {} as Record<string, unknown> }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => state.scope, useOptionalManagedZev: () => state.scope }))
vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: { id: 1, role: 'admin' } }) }))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (value: string) => value,
}))
vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}))
vi.mock('../src/lib/api/invoices', async importOriginal => ({
    ...await importOriginal(),
    fetchInvoicePeriodOverview: vi.fn(() => new Promise(() => {})),
}))

import { InvoicesPage } from '../src/pages/InvoicesPage'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach(cleanup => cleanup()))

async function render(embedded = false) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const snapshots: Array<{ empty: boolean; skeleton: boolean }> = []
    function Probe() {
        useLayoutEffect(() => {
            snapshots.push({
                empty: !!container.querySelector('.empty-state'),
                skeleton: !!container.querySelector('.skeleton-block'),
            })
        })
        return createElement(InvoicesPage, { embedded })
    }
    await act(async () => root.render(
        createElement(MemoryRouter, null,
            createElement(QueryClientProvider, { client },
                createElement(MantineProvider, null, createElement(Probe)),
            ),
        ),
    ))
    cleanups.push(() => {
        act(() => root.unmount())
        client.clear()
        container.remove()
    })
    return { container, snapshots }
}

describe('invoice page states', () => {
    for (const mode of ['loading', 'error', 'empty']) {
        it(`keeps the standalone title during scope ${mode}`, async () => {
            state.scope = {
                selectedZevId: '', selectedZev: null, refetch: vi.fn(),
                isLoading: mode === 'loading', isError: mode === 'error',
            }
            const page = await render()
            expect(page.container.querySelectorAll('h1')).toHaveLength(1)
            expect(page.container.querySelector('h1')?.textContent).toBe('pages.invoices.title')
        })
    }

    it('uses a skeleton before period initialization and while the initial query is pending', async () => {
        state.scope = {
            selectedZevId: '42',
            selectedZev: { id: '42', name: 'Review ZEV', billing_interval: 'monthly', start_date: '2026-01-01' },
            isLoading: false, isError: false, refetch: vi.fn(),
        }
        const page = await render()
        expect(page.snapshots[0]).toEqual({ empty: false, skeleton: true })
        expect(page.container.querySelector('.skeleton-block')).not.toBeNull()
        expect(page.container.querySelector('.empty-state')).toBeNull()
        expect(page.container.querySelectorAll('h1')).toHaveLength(1)
    })

    it('leaves the title to the host when embedded', async () => {
        state.scope = { selectedZevId: '', selectedZev: null, isLoading: false, isError: false, refetch: vi.fn() }
        const page = await render(true)
        expect(page.container.querySelector('h1')).toBeNull()
        expect(page.container.querySelector('.empty-state')).not.toBeNull()
    })
})
