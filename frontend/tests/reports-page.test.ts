import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

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
    downloadAllAnnualStatements: vi.fn(() => Promise.resolve(new Blob())),
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

function renderReportsPage() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient()
    const root = createRoot(container)
    act(() => {
        root.render(createElement(QueryClientProvider, { client }, createElement(ReportsPage)))
    })
    return {
        container,
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
    mockAuth.mockReturnValue({ user: { role: 'admin' } })
    mockManagedZev.mockReturnValue({ selectedZevId, selectedZev, managedZevs, isLoading: false })
}

async function changeYear(select: HTMLSelectElement, value: string) {
    await act(async () => {
        select.value = value
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
}

async function click(button: HTMLButtonElement) {
    await act(async () => {
        button.click()
    })
    await act(async () => {
        await new Promise((r) => setTimeout(r, 0))
    })
}

describe('ReportsPage role branches', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    it('owner with valid ZEV renders eyebrow, shared year selector, and both cards', () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        expect(container.textContent).toContain('Demo') // ZEV scope eyebrow
        expect(container.textContent).toContain('pages.reports.title')
        expect(container.textContent).toContain('pages.reports.annualStatement.ownerDescription')
        expect(container.textContent).toContain('pages.reports.annualStatement.downloadAll')
        expect(container.textContent).toContain('pages.reports.financialSummary.description')
        expect(container.textContent).not.toContain('pages.reports.selectZevTitle')
        expect(container.textContent).not.toContain('pages.reports.noZevTitle')
        // exactly one shared year selector for the whole page
        expect(container.querySelectorAll('select').length).toBe(1)
        unmount()
    })

    it('year selector defaults to last completed year', () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        const select = container.querySelector('select') as HTMLSelectElement
        expect(select.value).toBe(String(new Date().getFullYear() - 1))
        unmount()
    })

    it('shared year selector feeds both download calls', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        const select = container.querySelector('select') as HTMLSelectElement
        const targetYear = new Date().getFullYear() - 2
        await changeYear(select, String(targetYear))

        const buttons = Array.from(container.querySelectorAll('button')) as HTMLButtonElement[]
        const zipButton = buttons.find((b) => b.textContent === 'pages.reports.annualStatement.downloadAll')
        const financialButton = buttons.find((b) => b.textContent === 'pages.reports.financialSummary.download')
        expect(zipButton).toBeTruthy()
        expect(financialButton).toBeTruthy()

        await click(zipButton!)
        await click(financialButton!)

        expect(invoicesApi.downloadAllAnnualStatements).toHaveBeenCalledWith({ year: targetYear, zev_id: 'zev-1' })
        const financialArg = (invoicesApi.downloadFinancialSummary as any).mock.calls.at(-1)?.[0]
        expect(financialArg.year).toBe(targetYear)
        expect(financialArg.zev_id).toBe('zev-1')
        unmount()
    })

    it('owner without ZEV shows empty state and no download cards', () => {
        mockOwner({ selectedZevId: null, selectedZev: null, managedZevs: [] })

        const { container, unmount } = renderReportsPage()
        expect(container.textContent).toContain('pages.reports.noZevTitle')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.downloadAll')
        unmount()
    })

    it('stale ZEV selection shows select-guard and no cards (prevents 403)', () => {
        mockOwner({
            selectedZevId: 'stale-id',
            selectedZev: undefined,
            managedZevs: [{ id: 'other-id', name: 'Other' }],
        })

        const { container, unmount } = renderReportsPage()
        expect(container.textContent).toContain('pages.reports.selectZevTitle')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.downloadAll')
        unmount()
    })

    it('participant renders single PDF + financial summary, financial call has no zev_id', async () => {
        mockAuth.mockReturnValue({ user: { role: 'participant' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: null,
            selectedZev: null,
            managedZevs: [],
            isLoading: false,
        })

        const { container, unmount } = renderReportsPage()
        expect(container.textContent).toContain('pages.reports.annualStatement.description')
        expect(container.textContent).toContain('pages.reports.annualStatement.download')
        // owner ZIP text should not appear for participant
        expect(container.textContent).not.toContain('pages.reports.annualStatement.ownerDescription')

        // click participant financial summary download and assert zev_id not sent
        const buttons = Array.from(container.querySelectorAll('button')) as HTMLButtonElement[]
        // second card is financial summary (download)
        const financialBtn = buttons.find((b) => b.textContent === 'pages.reports.financialSummary.download')
        expect(financialBtn).toBeTruthy()
        await click(financialBtn!)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalled()
        const callArg = (invoicesApi.downloadFinancialSummary as any).mock.calls[0]?.[0]
        expect(callArg.zev_id).toBeUndefined()
        expect(callArg.year).toBeDefined()

        unmount()
    })
})
