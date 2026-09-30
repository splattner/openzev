import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter } from 'react-router-dom'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'en' } }),
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
    fetchAnnualReport: vi.fn(),
}))

vi.mock('../src/lib/api/exports', () => ({
    createAnnualStatementsExport: vi.fn(),
    fetchAnnualStatementExports: vi.fn(() => Promise.resolve([])),
    fetchExportJob: vi.fn(),
    downloadAnnualStatementsExport: vi.fn(() => Promise.resolve(new Blob())),
}))

vi.mock('../src/lib/downloadBlob', () => ({
    downloadBlob: vi.fn(),
}))

import { ReportsPage } from '../src/pages/ReportsPage'
import * as invoicesApi from '../src/lib/api/invoices'
import type { AnnualReport, AnnualReportBalance } from '../src/types/api'

// jsdom does not enable the React act() environment by default; without this
// flag every act() call warns and deferred work is not flushed reliably.
globalThis.IS_REACT_ACT_ENVIRONMENT = true

function renderReportsPage(component = ReportsPage) {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
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

const BALANCE: AnnualReportBalance = {
    produced_kwh: 10,
    consumed_kwh: 10,
    imported_kwh: 6,
    exported_kwh: 6,
    self_consumed_kwh: 4,
    self_consumption_rate: 40,
    self_sufficiency_rate: 40,
}

function makeReport(overrides: Partial<AnnualReport> = {}): AnnualReport {
    return {
        zev_id: 'zev-1',
        year: new Date().getFullYear() - 1,
        has_data: true,
        totals: BALANCE,
        previous_totals: { ...BALANCE, self_consumption_rate: 50, self_sufficiency_rate: 100 },
        months: Array.from({ length: 12 }, (_, i) => ({
            ...BALANCE,
            month: i + 1,
            previous_self_consumption_rate: null,
            previous_self_sufficiency_rate: null,
        })),
        participants: [
            {
                participant_id: 'p-1',
                participant_name: 'Pia Muster',
                consumed_kwh: 10,
                produced_kwh: 0,
                from_zev_kwh: 4,
                from_grid_kwh: 6,
                self_sufficiency_rate: 40,
                savings: {
                    local_kwh: '4.00',
                    local_chf: '0.80',
                    local_rp: '20.00',
                    grid_rp: '30.00',
                    hypothetical_chf: '1.20',
                    saved_chf: '0.40',
                },
            },
            {
                participant_id: 'p-2',
                participant_name: 'Paul Produzent',
                consumed_kwh: 0,
                produced_kwh: 10,
                from_zev_kwh: 0,
                from_grid_kwh: 0,
                self_sufficiency_rate: null,
                savings: null,
            },
        ],
        savings_total_chf: '0.40',
        ...overrides,
    }
}

describe('ReportsPage role branches', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
        vi.mocked(invoicesApi.fetchAnnualReport).mockResolvedValue(makeReport())
    })

    it('owner with valid ZEV renders the annual report and both yearly documents', async () => {
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        await flush()
        expect(container.textContent).toContain('Demo') // ZEV scope eyebrow
        expect(container.textContent).toContain('pages.reports.title')
        expect(container.textContent).toContain('pages.reports.financialSummary.ownerDescription')
        expect(container.textContent).toContain('pages.reports.financialSummary.download')
        expect(container.textContent).toContain('pages.reports.annualReport.stats.selfConsumptionRate')
        expect(container.textContent).toContain('pages.reports.documentsTitle')
        expect(container.textContent).toContain('pages.reports.annualStatement.ownerDescription')
        expect(findButton(container, 'pages.reports.annualStatement.prepare')).toBeTruthy()
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

describe('ReportsPage annual report', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
        mockOwner({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
        })
    })

    it('requests the selected ZEV and year', async () => {
        vi.mocked(invoicesApi.fetchAnnualReport).mockResolvedValue(makeReport())

        const { unmount } = renderReportsPage()
        await flush()
        expect(invoicesApi.fetchAnnualReport).toHaveBeenCalledWith({ zev_id: 'zev-1', year: new Date().getFullYear() - 1 })
        unmount()
    })

    it('shows the rates, the trend, and each participant\'s savings', async () => {
        vi.mocked(invoicesApi.fetchAnnualReport).mockResolvedValue(makeReport())

        const { container, unmount } = renderReportsPage()
        await flush()
        await flush()
        const kpis = container.querySelector('.kpi-row')!
        expect(kpis.textContent).toContain('40\u00a0%')
        expect(kpis.textContent).toContain('pages.reports.annualReport.hints.previousYear')
        expect(kpis.textContent).toContain('CHF 0.40')
        expect(container.textContent).toContain('pages.reports.annualReport.trend.title')

        const rows = Array.from(container.querySelectorAll('.participant-table tbody tr'))
        expect(rows.map((row) => row.querySelector('td')?.textContent)).toEqual(['Pia Muster', 'Paul Produzent'])
        expect(rows[0].textContent).toContain('CHF 0.80')
        expect(rows[0].textContent).toContain('CHF 1.20')
        // No invoices, no savings: the money columns stay empty rather than showing zero.
        expect(rows[1].textContent).toContain('—')
        expect(rows[1].textContent).not.toContain('CHF')
        expect(container.querySelector('.participant-table tfoot')?.textContent).toContain('CHF 0.40')
        unmount()
    })

    it('says so when the year has no metering data', async () => {
        vi.mocked(invoicesApi.fetchAnnualReport).mockResolvedValue(makeReport({ has_data: false }))

        const { container, unmount } = renderReportsPage()
        await flush()
        await flush()
        expect(container.textContent).toContain('pages.reports.annualReport.noData')
        expect(container.querySelector('.kpi-row')).toBeNull()
        // The yearly documents stay available regardless.
        expect(findButton(container, 'pages.reports.financialSummary.download')).toBeTruthy()
        unmount()
    })

    it('shows an error when the report cannot be loaded', async () => {
        vi.mocked(invoicesApi.fetchAnnualReport).mockRejectedValue(new Error('boom'))

        const { container, unmount } = renderReportsPage()
        await flush()
        await flush()
        expect(container.querySelector('[role="alert"]')?.textContent).toBe('pages.reports.annualReport.error')
        unmount()
    })
})
