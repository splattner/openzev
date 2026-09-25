import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

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
import { downloadBlob } from '../src/lib/downloadBlob'
import { deferred, flush, pdfBlob } from './pdf-test-utils'

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

function mockParticipant(id = 7) {
    mockAuth.mockReturnValue({ user: { id, role: 'participant', zev_name: 'Demo' } })
    mockManagedZev.mockReturnValue({
        selectedZevId: null,
        selectedZev: null,
        managedZevs: [],
        isLoading: false,
    })
}

async function changeYear(select: HTMLSelectElement, value: string) {
    await act(async () => {
        select.value = value
        select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await flush()
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

describe('ReportsPage participant entry', () => {
    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
    })

    it('year selector defaults to last completed year for participants', async () => {
        mockAuth.mockReturnValue({ user: { id: 7, role: 'participant' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: null,
            selectedZev: null,
            managedZevs: [],
            isLoading: false,
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        const select = container.querySelector('select') as HTMLSelectElement
        expect(select.value).toBe(String(new Date().getFullYear() - 1))
        unmount()
    })

    it('shared year selector drives the participant statement request', async () => {
        mockAuth.mockReturnValue({ user: { id: 7, role: 'participant' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: null,
            selectedZev: null,
            managedZevs: [],
            isLoading: false,
        })
        const targetYear = new Date().getFullYear() - 2
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(pdfBlob())

        const { container, unmount } = renderReportsPage()
        await flush()
        const select = container.querySelector('select') as HTMLSelectElement
        await changeYear(select, String(targetYear))

        expect(invoicesApi.downloadAnnualStatement).toHaveBeenLastCalledWith(
            { year: targetYear },
            expect.any(AbortSignal),
        )
        expect(invoicesApi.downloadFinancialSummary).not.toHaveBeenCalled()
        unmount()
    })

    it('participant renders document tabs with the statement selected, never the owner ZIP flow', async () => {
        mockAuth.mockReturnValue({ user: { id: 7, role: 'participant' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: null,
            selectedZev: null,
            managedZevs: [],
            isLoading: false,
        })
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(pdfBlob())

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('pages.reports.participantDescription')
        expect(container.textContent).toContain('pages.reports.annualStatement.description')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.ownerDescription')
        expect(container.textContent).not.toContain('pages.reports.annualStatement.prepare')

        const tabs = Array.from(container.querySelectorAll('[role="tab"]'))
        expect(tabs.map((tab) => tab.textContent)).toEqual([
            'pages.reports.annualStatement.title',
            'pages.reports.financialSummary.title',
        ])
        expect(tabs[0].getAttribute('aria-selected')).toBe('true')
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalled()
        expect(invoicesApi.downloadFinancialSummary).not.toHaveBeenCalled()
        unmount()
    })
})

describe('ReportsPage participant annual documents', () => {
    let objectUrlCount: number

    beforeEach(() => {
        document.body.innerHTML = ''
        vi.clearAllMocks()
        objectUrlCount = 0
        mockParticipant()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockReset()
        vi.mocked(invoicesApi.downloadFinancialSummary).mockReset()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(pdfBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(pdfBlob())
        vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:annual-${++objectUrlCount}`)
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    function statementBlob() {
        return new Blob(['statement'], { type: 'application/pdf' })
    }

    function taxBlob() {
        return new Blob(['tax'], { type: 'application/pdf' })
    }

    function tabs(container: HTMLElement) {
        return Array.from(container.querySelectorAll('[role="tab"]')) as HTMLElement[]
    }

    function selectTab(container: HTMLElement, titleKey: string) {
        const tab = tabs(container).find((candidate) => candidate.textContent === titleKey)!
        expect(tab).toBeTruthy()
        return click(tab as HTMLButtonElement)
    }

    it('loads the annual statement on entry without touching the tax endpoint', async () => {
        const blob = statementBlob()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(blob)
        const { container, unmount } = renderReportsPage()
        await flush()

        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledWith(
            { year: new Date().getFullYear() - 1 },
            expect.any(AbortSignal),
        )
        expect(invoicesApi.downloadFinancialSummary).not.toHaveBeenCalled()

        const region = container.querySelector('#yearly-documents-preview') as HTMLElement
        expect(region).toBeTruthy()
        const label = container.querySelector('label[for="participant-year-select"]') as HTMLLabelElement
        expect(label).toBeTruthy()
        expect(label.textContent).toContain('pages.reports.year')
        expect(container.querySelector('[role="tablist"]')).toBeTruthy()
        expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe(
            'pages.reports.documentTabs',
        )
        const [statementTab, taxTab] = tabs(container)
        expect(statementTab.getAttribute('aria-selected')).toBe('true')
        expect(taxTab.getAttribute('aria-selected')).toBe('false')
        expect(container.querySelector('[role="tabpanel"]')).toBeTruthy()
        const frames = container.querySelectorAll('iframe')
        expect(frames).toHaveLength(1)
        expect(frames[0].getAttribute('title')).toBe('pages.reports.documentTitle')
        expect(container.querySelectorAll('.pdf-frame a[target="_blank"]')).toHaveLength(1)
        expect(findButton(container, 'pdf.download')).toBeTruthy()
        expect(findButton(container, 'pdf.download')!.disabled).toBe(false)

        unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
    })

    it('generates the tax overview only on first selection and reuses both documents on revisit', async () => {
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())
        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')
        expect(container.querySelectorAll('iframe')).toHaveLength(1)

        await selectTab(container, 'pages.reports.annualStatement.title')
        await flush()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')
        unmount()
    })

    it('keeps a still-pending document usable when returning before it finishes', async () => {
        const taxGate = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockReturnValue(taxGate.promise)
        const { container, unmount } = renderReportsPage()
        await flush()

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(container.textContent).toContain('pages.reports.preparingDocument')

        await selectTab(container, 'pages.reports.annualStatement.title')
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')

        await act(async () => {
            taxGate.resolve(taxBlob())
            await taxGate.promise
        })
        await flush()
        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')
        unmount()
    })

    it('download and new-tab reuse the displayed blob without further HTTP', async () => {
        const year = new Date().getFullYear() - 1
        const blob = statementBlob()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(blob)
        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.querySelector('iframe')).toBeTruthy()

        await click(findButton(container, 'pdf.download')!)
        expect(downloadBlob).toHaveBeenCalledWith(blob, `annual-statement-${year}.pdf`)
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)

        const urlsBeforeTab = vi.mocked(URL.createObjectURL).mock.calls.length
        const popup = { opener: window, location: { replace: vi.fn() } }
        const openSpy = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
        const newTabLink = container.querySelector('.pdf-frame a') as HTMLAnchorElement
        await act(async () => {
            newTabLink.click()
        })
        await flush()
        await flush()

        expect(openSpy).toHaveBeenCalledWith('', '_blank')
        expect(popup.opener).toBeNull()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
        expect(vi.mocked(URL.createObjectURL).mock.calls.length).toBe(urlsBeforeTab + 1)
        expect(popup.location.replace).toHaveBeenCalledWith(`blob:annual-${objectUrlCount}`)
        unmount()
    })

    it('year stays enabled while loading; changing it preserves the tab, aborts the old and fetches only the active document', async () => {
        const initialYear = new Date().getFullYear() - 1
        const targetYear = new Date().getFullYear() - 2
        const seenSignals: AbortSignal[] = []
        const first = deferred<Blob>()
        const second = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockImplementation(({ year }, signal) => {
            seenSignals.push(signal!)
            return year === initialYear ? first.promise : second.promise
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        const select = container.querySelector('select') as HTMLSelectElement
        expect(select.disabled).toBe(false)

        await changeYear(select, String(targetYear))
        expect(seenSignals[0].aborted).toBe(true)
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(2)
        expect(invoicesApi.downloadFinancialSummary).not.toHaveBeenCalled()
        expect(tabs(container)[0].getAttribute('aria-selected')).toBe('true')
        expect(URL.revokeObjectURL).not.toHaveBeenCalled()
        expect(container.querySelector('iframe')).toBeNull()
        expect(container.textContent).toContain('pages.reports.preparingDocument')

        await act(async () => {
            first.resolve(statementBlob())
            await first.promise
        })
        await flush()
        expect(URL.createObjectURL).not.toHaveBeenCalled()
        expect(container.querySelector('iframe')).toBeNull()

        await act(async () => {
            second.resolve(statementBlob())
            await second.promise
        })
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')
        expect(URL.createObjectURL).toHaveBeenCalledOnce()

        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        await changeYear(select, String(initialYear))
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(3)
        unmount()
    })

    it('changing years while Tax Overview is selected preserves the tab and fetches only the tax document', async () => {
        const initialYear = new Date().getFullYear() - 1
        const targetYear = new Date().getFullYear() - 2
        const seenSignals: AbortSignal[] = []
        const pendingTax = deferred<Blob>()
        const nextTax = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockImplementation(({ year }, signal) => {
            seenSignals.push(signal!)
            return year === initialYear ? pendingTax.promise : nextTax.promise
        })

        const { container, unmount } = renderReportsPage()
        await flush()
        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(tabs(container)[1].getAttribute('aria-selected')).toBe('true')

        const select = container.querySelector('select') as HTMLSelectElement
        await changeYear(select, String(targetYear))
        expect(seenSignals[0].aborted).toBe(true)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(2)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenLastCalledWith(
            { year: targetYear },
            expect.any(AbortSignal),
        )
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(tabs(container)[1].getAttribute('aria-selected')).toBe('true')
        expect(container.querySelector('iframe')).toBeNull()
        expect(container.textContent).toContain('pages.reports.preparingDocument')

        await act(async () => {
            pendingTax.resolve(taxBlob())
            await pendingTax.promise
        })
        await flush()
        expect(container.querySelector('iframe')).toBeNull()

        await act(async () => {
            nextTax.resolve(taxBlob())
            await nextTax.promise
        })
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')
        unmount()
    })

    it('tax download reuses the displayed blob without further HTTP', async () => {
        const year = new Date().getFullYear() - 1
        const statement = statementBlob()
        const tax = taxBlob()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statement)
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(tax)
        const { container, unmount } = renderReportsPage()
        await flush()
        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(container.querySelector('iframe')).toBeTruthy()

        await click(findButton(container, 'pdf.download')!)
        expect(downloadBlob).toHaveBeenCalledWith(tax, `financial-summary-${year}.pdf`)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        unmount()
    })

    it('revisiting a failed tab preserves its error until Retry', async () => {
        vi.mocked(invoicesApi.downloadAnnualStatement).mockRejectedValueOnce(new Error('render failed'))
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.textContent).toContain('pages.reports.annualStatement.error')

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')

        await selectTab(container, 'pages.reports.annualStatement.title')
        await flush()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(container.textContent).toContain('pages.reports.annualStatement.error')
        expect(container.querySelector('[role="alert"]')).toBeTruthy()
        expect(container.querySelector('iframe')).toBeNull()
        unmount()
    })

    it('cleans up both loaded documents when the user changes and on unmount', async () => {
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const { container, rerender, unmount } = renderReportsPage()
        await flush()
        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        await selectTab(container, 'pages.reports.annualStatement.title')
        await flush()
        expect(URL.createObjectURL).toHaveBeenCalledTimes(2)

        mockAuth.mockReturnValue({ user: { id: 8, role: 'participant', zev_name: 'Demo' } })
        rerender()
        await flush()

        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-2')
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(2)
        expect(tabs(container)[0].getAttribute('aria-selected')).toBe('true')
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-3')

        unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-3')
    })

    it('revokes both loaded documents on unmount and when the participant changes role', async () => {
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const unmounted = renderReportsPage()
        await flush()
        await selectTab(unmounted.container, 'pages.reports.financialSummary.title')
        await flush()
        expect(URL.createObjectURL).toHaveBeenCalledTimes(2)
        unmounted.unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-2')

        vi.clearAllMocks()
        objectUrlCount = 0
        mockParticipant()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())
        const roleChange = renderReportsPage()
        await flush()
        await selectTab(roleChange.container, 'pages.reports.financialSummary.title')
        await flush()
        expect(URL.createObjectURL).toHaveBeenCalledTimes(2)

        mockAuth.mockReturnValue({ user: { id: 7, role: 'zev_owner' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1', name: 'Demo' }],
            isLoading: false,
        })
        roleChange.rerender()
        await flush()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-2')
        expect(roleChange.container.querySelector('#yearly-documents-preview')).toBeNull()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        roleChange.unmount()
    })

    it('cleans up active and inactive documents when the user changes and on unmount', async () => {
        const taxGate = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockReturnValue(taxGate.promise)

        const { container, rerender, unmount } = renderReportsPage()
        await flush()
        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()

        mockAuth.mockReturnValue({ user: { id: 8, role: 'participant', zev_name: 'Demo' } })
        rerender()
        await flush()

        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(2)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(tabs(container)[0].getAttribute('aria-selected')).toBe('true')

        await act(async () => {
            taxGate.resolve(taxBlob())
            await taxGate.promise
        })
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')

        unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-2')
    })

    it('retry affects only its document, keeps no stale actions, and focuses its status', async () => {
        const statementRetry = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement)
            .mockRejectedValueOnce(new Error('render failed'))
            .mockReturnValueOnce(statementRetry.promise)
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const { container, unmount } = renderReportsPage()
        await flush()

        expect(container.textContent).toContain('pages.reports.annualStatement.error')
        expect(container.querySelector('[role="alert"]')).toBeTruthy()
        expect(container.querySelector('iframe')).toBeNull()
        expect(container.querySelector('.pdf-frame a')).toBeNull()
        expect(findButton(container, 'pdf.download')!.disabled).toBe(true)

        const retryButton = findButton(container, 'common.retry')!
        await click(retryButton)
        await flush()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(2)
        expect(invoicesApi.downloadFinancialSummary).not.toHaveBeenCalled()
        expect(container.textContent).toContain('pages.reports.preparingDocument')
        expect(container.querySelector('[role="alert"]')).toBeNull()
        expect(document.activeElement?.classList.contains('yearly-document-status')).toBe(true)

        await act(async () => {
            statementRetry.resolve(statementBlob())
            await statementRetry.promise
        })
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')
        expect(document.activeElement?.classList.contains('yearly-document-status')).toBe(true)
        expect(document.activeElement?.tagName).not.toBe('BODY')

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        unmount()
    })

    it('retains the other loaded document while Retry replaces only the failed document', async () => {
        const statementRetry = deferred<Blob>()
        vi.mocked(invoicesApi.downloadAnnualStatement)
            .mockRejectedValueOnce(new Error('render failed'))
            .mockReturnValueOnce(statementRetry.promise)
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const { container, unmount } = renderReportsPage()
        await flush()
        expect(container.querySelector('[role="alert"]')).toBeTruthy()

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')
        await selectTab(container, 'pages.reports.annualStatement.title')
        await flush()
        expect(container.querySelector('[role="alert"]')).toBeTruthy()

        await click(findButton(container, 'common.retry')!)
        await flush()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(2)
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')).toBeNull()

        await act(async () => {
            statementRetry.resolve(statementBlob())
            await statementRetry.promise
        })
        await flush()
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-2')

        await selectTab(container, 'pages.reports.financialSummary.title')
        await flush()
        expect(invoicesApi.downloadFinancialSummary).toHaveBeenCalledTimes(1)
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('blob:annual-1')
        unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-1')
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:annual-2')
    })

    it('does not fetch participant documents for a ZEV owner', async () => {
        mockAuth.mockReturnValue({ user: { id: 3, role: 'zev_owner' } })
        mockManagedZev.mockReturnValue({
            selectedZevId: 'zev-1',
            selectedZev: { id: 'zev-1', name: 'Demo' },
            managedZevs: [{ id: 'zev-1' }],
            isLoading: false,
        })

        const { container, unmount } = renderReportsPage()
        await flush()

        expect(findButton(container, 'pages.reports.financialSummary.download')).toBeTruthy()
        expect(container.querySelector('#yearly-documents-preview')).toBeNull()
        expect(invoicesApi.downloadAnnualStatement).not.toHaveBeenCalled()
        unmount()
    })

    it('renders the same documents on both participant routes', async () => {
        async function renderAtPath(path: string) {
            const holder = document.createElement('div')
            document.body.appendChild(holder)
            const root = createRoot(holder)
            const client = new QueryClient()
            act(() => {
                root.render(createElement(
                    MemoryRouter,
                    { initialEntries: [path] },
                    createElement(
                        MantineProvider,
                        null,
                        createElement(QueryClientProvider, { client }, createElement(
                            Routes,
                            null,
                            createElement(Route, { path: '/me/statement', element: createElement(ReportsPage) }),
                            createElement(Route, { path: '/reports', element: createElement(ReportsPage) }),
                        )),
                    ),
                ))
            })
            await flush()
            return {
                holder,
                unmount: () => {
                    act(() => root.unmount())
                    holder.remove()
                },
            }
        }

        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())

        const first = await renderAtPath('/me/statement')
        expect(first.holder.querySelector('#yearly-documents-preview')).toBeTruthy()
        expect(first.holder.querySelector('iframe')).toBeTruthy()
        first.unmount()

        vi.clearAllMocks()
        vi.mocked(invoicesApi.downloadAnnualStatement).mockResolvedValue(statementBlob())
        vi.mocked(invoicesApi.downloadFinancialSummary).mockResolvedValue(taxBlob())

        const second = await renderAtPath('/reports')
        expect(second.holder.querySelector('#yearly-documents-preview')).toBeTruthy()
        expect(second.holder.querySelector('iframe')).toBeTruthy()
        expect(invoicesApi.downloadAnnualStatement).toHaveBeenCalledTimes(1)
        second.unmount()
    })
})
