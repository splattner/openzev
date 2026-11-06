import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeliveredDocument } from '../src/types/api'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => (options?.title ? `${key}:${options.title}` : key) }),
}))

const mockAuth = vi.fn()
vi.mock('../src/lib/auth', () => ({ useAuth: () => mockAuth() }))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/appSettings')>()),
    useAppSettings: () => ({ settings: undefined, isLoading: false, isError: false }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/api/inbox', () => ({
    listInboxDocuments: vi.fn(),
    downloadInboxDocument: vi.fn(() => Promise.resolve(new Blob(['%PDF-']))),
}))
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob: vi.fn() }))

import { DocumentsPage } from '../src/pages/DocumentsPage'
import * as inboxApi from '../src/lib/api/inbox'
import { downloadBlob } from '../src/lib/downloadBlob'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function doc(overrides: Partial<DeliveredDocument>): DeliveredDocument {
    return {
        id: 'd', zev: 'z1', zev_name: 'Sonnenhof', participant: 'p1', participant_name: 'Anna', kind: 'operator',
        title: 'House rules', document_number: '', period_start: null, period_end: null, file_name: 'rules.pdf',
        size_bytes: 2048, sha256: '', delivered_at: '2026-03-04T10:00:00Z', delivered_by_name: null,
        superseded_at: null, superseded_by: null, withdrawn_at: null, batch_id: null, invoice: null,
        invoice_status: null, contract_issue: null, ...overrides,
    }
}

const membership = (zev: string, name: string, participantId: string) => ({
    zev, zev_name: name, zev_disabled: false, zev_billing_interval: 'monthly', access: null,
    participants: [{ id: participantId, valid_from: '2026-01-01', valid_to: null, live: true }],
})

function render() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => root.render(createElement(
        MemoryRouter, null,
        createElement(MantineProvider, null,
            createElement(QueryClientProvider, { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }, createElement(DocumentsPage))),
    )))
    return { container, unmount: () => { act(() => root.unmount()); container.remove() } }
}

/** Let the query settle: flush until the page shows `text`, rather than guessing how many ticks it needs. */
async function settled(page: { container: HTMLElement }, text: string) {
    for (let attempt = 0; attempt < 20 && !page.container.textContent?.includes(text); attempt += 1) await flush()
}

describe('DocumentsPage', () => {
    beforeEach(() => {
        mockAuth.mockReturnValue({ user: { id: 1, username: 'anna', memberships: [membership('z1', 'Sonnenhof', 'p1')] } })
    })
    afterEach(() => vi.clearAllMocks())

    it('says nothing has been delivered when the list is empty', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([])
        const page = render()
        await settled(page, 'inbox.empty.title')
        expect(page.container.textContent).toContain('inbox.empty.title')
        page.unmount()
    })

    it('lists the documents in one table like the other lists, marks a superseded one and keeps only the account\'s own rows', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'b', title: 'House rules' }),
            doc({ id: 'a', title: 'Statement 2025', kind: 'annual_statement', period_start: '2025-01-01', superseded_at: '2026-04-01T00:00:00Z' }),
            doc({ id: 'c', title: 'Someone else', participant: 'other' }),
        ])
        const page = render()
        await settled(page, 'Statement 2025')

        expect(page.container.querySelectorAll('h2')).toHaveLength(0)
        expect(page.container.querySelectorAll('.table-card thead th')).toHaveLength(4)
        const rows = [...page.container.querySelectorAll('tbody tr')].map((row) => row.textContent)
        expect(rows).toHaveLength(2)
        expect(rows[0]).toContain('House rules')
        expect(rows[1]).toContain('Statement 2025')
        expect(rows[1]).toContain('inbox.standing.superseded')
        expect(page.container.textContent).not.toContain('Someone else')
        page.unmount()
    })

    it('narrows to one year when there is more than one', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'b', title: 'House rules' }),
            doc({ id: 'a', title: 'Statement 2025', kind: 'annual_statement', period_start: '2025-01-01' }),
        ])
        const page = render()
        await settled(page, 'Statement 2025')
        const select = page.container.querySelector('select[aria-label="inbox.outbox.year"]') as HTMLSelectElement
        expect([...select.options].map((option) => option.value)).toEqual(['', '2026', '2025'])

        await act(async () => {
            select.value = '2025'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await flush()
        expect([...page.container.querySelectorAll('tbody tr')].map((row) => row.textContent)).toEqual([
            expect.stringContaining('Statement 2025'),
        ])
        page.unmount()
    })

    it('offers the kind as a select for a phone, next to the chips, and filters by it', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'b', title: 'House rules' }),
            doc({ id: 'a', title: 'Statement 2025', kind: 'annual_statement', period_start: '2026-01-01' }),
        ])
        const page = render()
        await settled(page, 'Statement 2025')

        expect(page.container.querySelector('.doc-filter-wide .filter-tabs')).not.toBeNull()
        const select = page.container.querySelector('.doc-filter-narrow select') as HTMLSelectElement
        expect([...select.options].map((option) => option.value)).toEqual(['all', 'annual_statement', 'operator'])

        await act(async () => {
            select.value = 'operator'
            select.dispatchEvent(new Event('change', { bubbles: true }))
        })
        await flush()
        expect([...page.container.querySelectorAll('tbody tr')].map((row) => row.textContent)).toEqual([
            expect.stringContaining('House rules'),
        ])
        page.unmount()
    })

    it('leaves out the empty Status column when no row has anything to say', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([doc({ id: 'b', title: 'House rules' })])
        const page = render()
        await settled(page, 'House rules')

        const headers = [...page.container.querySelectorAll('.doc-wide th')].map((cell) => cell.textContent)
        expect(headers).not.toContain('inbox.outbox.col.status')
        expect(page.container.querySelectorAll('.doc-wide tbody tr td')).toHaveLength(3)
        page.unmount()
    })

    it('shows a cancelled invoice as plain text with its badge and downloads a document through the API', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'inv', title: 'RE-1', kind: 'invoice', invoice: 'invoice-1', invoice_status: 'cancelled' }),
        ])
        const page = render()
        await settled(page, 'RE-1')

        // A participant has no live invoice to open (#862): the row is not a link.
        expect(page.container.querySelector('a[href^="/billing/invoices/"]')).toBeNull()
        expect(page.container.textContent).toContain('inbox.standing.cancelled')
        const button = page.container.querySelector('tbody button') as HTMLButtonElement
        await act(async () => { button.click() })
        await flush()
        expect(inboxApi.downloadInboxDocument).toHaveBeenCalledWith('inv')
        expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), 'rules.pdf')
        page.unmount()
    })

    it('offers a community filter only with more than one membership', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([doc({ id: 'a' })])
        const single = render()
        await settled(single, 'House rules')
        expect(single.container.querySelector('select')).toBeNull()
        single.unmount()

        mockAuth.mockReturnValue({
            user: { id: 1, username: 'anna', memberships: [membership('z1', 'Sonnenhof', 'p1'), membership('z2', 'Bergblick', 'p2')] },
        })
        const several = render()
        await settled(several, 'House rules')
        expect(several.container.querySelector('select')).not.toBeNull()
        several.unmount()
    })
})
