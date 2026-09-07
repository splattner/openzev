import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

/**
 * Render coverage for the page an invoice's QR opens.
 *
 * Two things make this page worth rendering in a test rather than trusting to
 * types. It is served to someone with **no session, no navigation and no
 * support channel** — a crash there is a dead end, and the one time this code
 * met a browser it white-screened on a payload shape no unit test had reason
 * to construct. And it is the one screen that must speak the *document's*
 * language rather than the reader's, which is invisible to every check that
 * does not actually render it.
 */

const fixedT = vi.fn((key: string) => key)
const getFixedT = vi.fn(() => fixedT)
const changeLanguage = vi.fn()

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string) => `browser:${key}`,
        i18n: { language: 'en', getFixedT, changeLanguage },
    }),
}))

const mockParams = vi.fn(() => ({ prefix: 'abc123' }))
const mockSearch = vi.fn(() => [new URLSearchParams('s=sekret')])

vi.mock('react-router-dom', () => ({
    useParams: () => mockParams(),
    useSearchParams: () => mockSearch(),
}))

const fetchPublicInvoice = vi.fn()
const fetchPublicInvoiceCharts = vi.fn()

vi.mock('../src/lib/api/public', () => ({
    fetchPublicInvoice: (...args: unknown[]) => fetchPublicInvoice(...args),
    fetchPublicInvoiceCharts: (...args: unknown[]) => fetchPublicInvoiceCharts(...args),
    publicInvoicePdfUrl: () => '/pdf',
    requestMagicLink: vi.fn(() => Promise.resolve()),
}))

import { PublicInvoicePage } from '../src/pages/PublicInvoicePage'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const invoice = (overrides = {}) => ({
    invoice_number: 'R-2026-001',
    zev_name: 'ZEV Musterweg',
    participant_name: 'Anna Muster',
    language: 'fr',
    period_start: '2026-01-01',
    period_end: '2026-01-31',
    status: 'sent',
    is_paid: false,
    total_chf: '238.87',
    currency: 'CHF',
    energy_summary: null,
    items: [
        { category: 'energy', description: 'Solarstrom ZEV', quantity: '320.5', unit: 'kWh', total_chf: '72.11' },
    ],
    has_pdf: true,
    ...overrides,
})

/**
 * Render and let every settled query reach the DOM.
 *
 * One `act` flushes a single round of microtasks, which is not enough: the
 * invoice query resolves, then the charts query it enables resolves after it.
 * Without draining, assertions land on whichever frame the scheduler happened
 * to stop at — and pass or fail by test order rather than by behaviour.
 */
async function renderPage() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const root = createRoot(container)
    await act(async () => {
        root.render(
            createElement(QueryClientProvider, { client }, createElement(PublicInvoicePage)),
        )
    })
    for (let i = 0; i < 5; i += 1) {
        await act(async () => {
            await new Promise((resolve) => setTimeout(resolve, 0))
        })
    }
    return {
        container,
        unmount: () => {
            act(() => root.unmount())
            container.remove()
        },
    }
}

beforeEach(() => {
    vi.clearAllMocks()
    fixedT.mockImplementation((key: string) => key)
    getFixedT.mockReturnValue(fixedT)
    fetchPublicInvoice.mockResolvedValue(invoice())
    fetchPublicInvoiceCharts.mockResolvedValue({ title: '', intro: '', charts: [] })
})

describe('PublicInvoicePage language', () => {
    it('renders in the language the invoice was issued in', async () => {
        const { unmount } = await renderPage()

        expect(getFixedT).toHaveBeenCalledWith('fr')
        unmount()
    })

    it('never switches the app language', async () => {
        // `changeLanguage` persists to localStorage and re-renders every
        // mounted tree, so it would leave this visitor's whole app in the
        // ZEV's language long after they closed the invoice.
        const { unmount } = await renderPage()

        expect(changeLanguage).not.toHaveBeenCalled()
        unmount()
    })

    it('marks up the page with the document language, not the document root', async () => {
        const { container, unmount } = await renderPage()

        expect(container.querySelector('.public-invoice-page')?.getAttribute('lang')).toBe('fr-CH')
        expect(document.documentElement.lang).not.toBe('fr-CH')
        unmount()
    })

    it('falls back to the browser translation before the invoice has loaded', async () => {
        // Until the payload names a language there is nothing better to use.
        fetchPublicInvoice.mockReturnValue(new Promise(() => {}))

        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('browser:pages.publicInvoice.loading')
        expect(getFixedT).not.toHaveBeenCalled()
        unmount()
    })
})

describe('PublicInvoicePage rendering', () => {
    it('renders the invoice without charts', async () => {
        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('ZEV Musterweg')
        expect(container.textContent).toContain('Solarstrom ZEV')
        unmount()
    })

    it('survives a charts payload with no charts key', async () => {
        // The shape that white-screened in production: a cached payload from
        // before the response was restructured.
        fetchPublicInvoiceCharts.mockResolvedValue({} as never)

        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('ZEV Musterweg')
        unmount()
    })

    it('survives a failing charts request', async () => {
        fetchPublicInvoiceCharts.mockRejectedValue(new Error('boom'))

        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('ZEV Musterweg')
        unmount()
    })

    it('renders an invoice with no line items', async () => {
        fetchPublicInvoice.mockResolvedValue(invoice({ items: [] }))

        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('ZEV Musterweg')
        unmount()
    })

    it('shows the invalid-link card when the request 404s', async () => {
        fetchPublicInvoice.mockRejectedValue(new Error('404'))

        const { container, unmount } = await renderPage()

        expect(container.textContent).toContain('invalidTitle')
        unmount()
    })
})
