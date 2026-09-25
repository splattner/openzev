import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k }),
}))

const mockAuth = vi.fn()
const mockManagedZev = vi.fn()

vi.mock('../src/lib/auth', () => ({
    useAuth: () => mockAuth(),
}))

vi.mock('../src/lib/managedZev', () => ({
    useManagedZev: () => mockManagedZev(),
}))

vi.mock('../src/lib/api/invoices', () => ({
    downloadAnnualStatement: vi.fn(() => Promise.resolve(new Blob())),
    downloadFinancialSummary: vi.fn(() => Promise.resolve(new Blob())),
}))

vi.mock('../src/lib/downloadBlob', () => ({
    downloadBlob: vi.fn(),
}))

import { ReportsPage } from '../src/pages/ReportsPage'
import * as invoicesApi from '../src/lib/api/invoices'

// jsdom does not enable the React act() environment by default; without this
// flag every act() call warns and deferred work is not flushed reliably.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function renderReportsPage(component = ReportsPage) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    const render = (target = component) => createElement(
        MemoryRouter,
        null,
        createElement(
            MantineProvider,
            null,
            createElement(QueryClientProvider, { client }, createElement(target)),
        ),
    )
    act(() => {
        root.render(render())
    })
    return {
        container,
        rerender: (target = component) => act(() => root.render(render(target))),
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

function mockOwner({ selectedZevId, selectedZev, managedZevs }: {
    selectedZevId: string | null
    selectedZev?: { id: string; name: string } | null
    managedZevs: Array<{ id: string; name?: string }>
}) {
    mockAuth.mockReturnValue({ user: { id: 1, role: 'admin' } })
    mockManagedZev.mockReturnValue({ selectedZevId, selectedZev, managedZevs, isLoading: false })
}

async function click(button: HTMLButtonElement) {
    await act(async () => {
        button.click()
    })
    await flush()
}

function findButton(container: HTMLElement, text: string): HTMLButtonElement | undefined {
    return (Array.from(container.querySelectorAll('button')) as HTMLButtonElement[]).find(
        (button) => button.textContent === text,
    )
}

describe('ReportsPage role branches', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    it('owner with valid ZEV renders the tax overview and analytics roadmap', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('Demo') // ZEV scope eyebrow
        expect(container.textContent).toContain('pages.reports.title')
        expect(container.textContent).toContain('pages.reports.financialSummary.ownerDescription')
        expect(container.textContent).toContain('pages.reports.financialSummary.download')
        expect(container.textContent).toContain('pages.reports.ownerComing.title')
        expect(container.textContent).toContain('pages.reports.ownerComing.description')
        expect(container.querySelector('a[href="/billing/statements"]')).toBeNull()
        expect(container.textContent).not.toContain('pages.reports.annualStatement.ownerDescription')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.downloadAll')
        expect(container.textContent).not.toContain('pages.reports.selectZevTitle')
        expect(container.textContent).not.toContain('pages.reports.noZevTitle')
        expect(findButton(container, 'pages.reports.financialSummary.download')).toBeTruthy()
        expect(container.querySelector('#yearly-documents-preview')).toBeNull()
        expect(invoicesApi.downloadAnnualStatement).not.toHaveBeenCalled()
        const button = Array.from(container.querySelectorAll('button')).find(
            (candidate) => candidate.textContent === 'pages.reports.financialSummary.download',
        )
        expect(button).toBeTruthy()
        await click(button!)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledWith({ year: new Date().getFullYear() - 1, zev_id: 'zev-1' })
        unmount()
    })

    it('owner with several communities still renders the scope eyebrow', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }, { id: 'zev-2' }],
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('Demo')
        expect(container.textContent).toContain('pages.reports.title')
        unmount()
    })

    it('year selector defaults to last completed year', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        const ownerSelect = container.querySelector('select') as HTMLSelectElement
        expect(ownerSelect.value).toBe(String(new Date().getFullYear() - 1))
        unmount()
    })




    it('owner without ZEV shows empty state and no cards', async () => {
        mockOwner({ selectedZevId: null, selectedZev: null, managedZevs: [] })

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('pages.reports.noZevTitle')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.prepare')
        unmount()
    })

    it('stale ZEV selection shows select-guard and no cards (prevents 403)', async () => {
        mockOwner({
            selectedZevId: 'stale-id',
            selectedZev: undefined,
            managedZevs: [{ id: 'other-id', name: 'Other' }],
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('pages.reports.selectZevTitle')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.prepare')
        unmount()
    })


})
