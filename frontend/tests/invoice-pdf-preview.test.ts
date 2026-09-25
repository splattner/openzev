import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { InvoiceDetailPage } from '../src/pages/InvoiceDetailPage'
import {
    fetchInvoice,
    fetchInvoicePdfBlob,
    generateInvoicePdf,
} from '../src/lib/api/invoices'
import { deferred, flush, pdfBlob } from './pdf-test-utils'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('../src/lib/auth', () => ({
    useAuth: () => ({ user: { id: 7, role: 'participant' } }),
}))

vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {}, isLoading: false }),
    formatShortDate: (value: string | null | undefined) => value ?? '',
}))

vi.mock('../src/lib/api/invoices', () => ({
    fetchInvoice: vi.fn(),
    fetchInvoicePdfBlob: vi.fn(),
    generateInvoicePdf: vi.fn(),
    revokeInvoiceAccessLink: vi.fn(),
}))

const invoice = {
    id: 'invoice-1',
    invoice_number: 'R-2026-1',
    zev_name: 'Demo',
    participant_name: 'Example Participant',
    period_start: '2026-01-01',
    period_end: '2026-03-31',
    status: 'sent',
    total_chf: '100.00',
    subtotal_chf: '92.59',
    vat_chf: '7.41',
    total_local_kwh: '100',
    total_grid_kwh: '50',
    total_feed_in_kwh: '10',
    access_link: null,
    pdf_url: '/media/invoices/invoice.pdf',
}

async function renderInvoiceDetail() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    const client = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    })

    act(() => {
        root.render(createElement(
            MemoryRouter,
            { initialEntries: ['/billing/invoices/invoice-1'] },
            createElement(
                QueryClientProvider,
                { client },
                createElement(
                    MantineProvider,
                    null,
                    createElement(Routes, null, createElement(Route, {
                        path: '/billing/invoices/:invoiceId',
                        element: createElement(InvoiceDetailPage),
                    })),
                ),
            ),
        ))
    })

    return {
        container,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

async function waitFor(predicate: () => boolean) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
        if (predicate()) return
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 10))
        })
    }
    throw new Error('Timed out waiting for invoice preview state')
}

describe('InvoiceDetailPage PDF preview lifecycle', () => {
    let objectUrlCount: number

    beforeEach(() => {
        document.body.innerHTML = ''
        objectUrlCount = 0
        vi.mocked(fetchInvoice).mockResolvedValue(invoice as never)
        vi.mocked(fetchInvoicePdfBlob).mockReset()
        vi.mocked(generateInvoicePdf).mockReset()
        vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:invoice-${++objectUrlCount}`)
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('keeps the viewer hidden while loading, then embeds and revokes the stored PDF', async () => {
        const pending = deferred<Blob>()
        vi.mocked(fetchInvoicePdfBlob).mockReturnValue(pending.promise)
        const { container, unmount } = await renderInvoiceDetail()

        await waitFor(() => vi.mocked(fetchInvoicePdfBlob).mock.calls.length === 1)
        expect(container.querySelector('iframe')).toBeNull()
        expect(container.textContent).not.toContain('common.error')

        await act(async () => {
            pending.resolve(pdfBlob())
            await pending.promise
        })
        await flush()

        const frame = container.querySelector('iframe') as HTMLIFrameElement
        expect(frame.getAttribute('src')).toBe('blob:invoice-1')
        expect(frame.getAttribute('title')).toBe('pages.invoiceDetail.title')
        expect(container.querySelector('.pdf-frame a')?.getAttribute('href')).toBe('blob:invoice-1')

        unmount()
        expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:invoice-1')
    })

    it('shows only the error when the stored PDF cannot be fetched', async () => {
        vi.mocked(fetchInvoicePdfBlob).mockRejectedValue(new Error('fetch failed'))
        const { container, unmount } = await renderInvoiceDetail()

        await waitFor(() => container.textContent?.includes('common.error') ?? false)

        expect(container.querySelector('iframe')).toBeNull()
        expect(container.querySelector('.pdf-frame')).toBeNull()
        expect(container.textContent).not.toContain('pdf.noDocument')
        unmount()
    })

    it('opens a new tab from its own fetch so it survives preview revocation', async () => {
        const firstBlob = pdfBlob()
        const newTabBlob = pdfBlob()
        const pendingTabFetch = deferred<Blob>()
        vi.mocked(fetchInvoicePdfBlob)
            .mockResolvedValueOnce(firstBlob)
            .mockReturnValueOnce(pendingTabFetch.promise)
        const { container, unmount } = await renderInvoiceDetail()

        await waitFor(() => container.querySelector('iframe') !== null)
        expect(vi.mocked(fetchInvoicePdfBlob)).toHaveBeenCalledTimes(1)

        const popup = { opener: window, location: { replace: vi.fn() } }
        const openSpy = vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window)
        const newTabLink = container.querySelector('.pdf-frame a') as HTMLAnchorElement
        await act(async () => {
            newTabLink.click()
        })

        expect(openSpy).toHaveBeenCalledWith('', '_blank')
        expect(popup.opener).toBeNull()
        expect(vi.mocked(fetchInvoicePdfBlob)).toHaveBeenCalledTimes(2)

        await act(async () => {
            pendingTabFetch.resolve(newTabBlob)
            await pendingTabFetch.promise
        })
        await flush()

        expect(URL.createObjectURL).toHaveBeenCalledTimes(2)
        expect(popup.location.replace).toHaveBeenCalledWith('blob:invoice-2')
        unmount()
    })
})
