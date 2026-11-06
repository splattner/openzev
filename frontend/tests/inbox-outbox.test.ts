import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DeliveredDocument } from '../src/types/api'
import { flush } from './pdf-test-utils'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/appSettings', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/lib/appSettings')>()),
    useAppSettings: () => ({ settings: undefined, isLoading: false, isError: false }),
}))
vi.mock('../src/lib/toast', () => ({ useToast: () => ({ pushToast: vi.fn() }) }))
vi.mock('../src/lib/managedZev', () => ({ useManagedZev: () => ({ selectedZevId: 'z1' }) }))
let canWrite = true
vi.mock('../src/lib/communityAccess', () => ({ useCommunityAccess: () => ({ canWriteSelectedCommunity: canWrite }) }))
vi.mock('../src/lib/api/inbox', () => ({
    listInboxDocuments: vi.fn(),
    withdrawInboxDocument: vi.fn(),
    downloadInboxDocument: vi.fn(),
}))
vi.mock('../src/lib/api/zev', () => ({
    fetchParticipants: vi.fn(() => Promise.resolve([
        { id: 'p1', zev: 'z1', first_name: 'Anna', last_name: 'A', user: 7, valid_to: null },
        { id: 'p2', zev: 'z1', first_name: 'Ben', last_name: 'B', user: null, valid_to: null },
    ])),
}))
vi.mock('../src/lib/downloadBlob', () => ({ downloadBlob: vi.fn() }))
vi.mock('../src/features/inbox/UploadDocumentDialog', () => ({ UploadDocumentDialog: () => null }))
vi.mock('../src/features/inbox/IssueReportsDialog', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../src/features/inbox/IssueReportsDialog')>()),
    IssueReportsDialog: () => null,
}))

import { Outbox } from '../src/features/inbox/Outbox'
import * as inboxApi from '../src/lib/api/inbox'

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

function render() {
    const container = document.createElement('div')
    document.body.appendChild(container)
    const root = createRoot(container)
    act(() => root.render(createElement(
        MantineProvider, null,
        createElement(QueryClientProvider, { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }, createElement(Outbox)),
    )))
    return { container, unmount: () => { act(() => root.unmount()); container.remove() } }
}

async function settled(page: { container: HTMLElement }, text: string) {
    for (let attempt = 0; attempt < 20 && !page.container.textContent?.includes(text); attempt += 1) await flush()
}

const headers = (container: HTMLElement) =>
    Array.from(container.querySelectorAll('.doc-wide th')).map((cell) => cell.textContent)

describe('Outbox table', () => {
    afterEach(() => { vi.clearAllMocks(); canWrite = true })

    it('leaves out the empty Status column when no row has a badge', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([doc({ id: 'a', participant: 'p1' })])
        const page = render()
        await settled(page, 'House rules')

        expect(headers(page.container)).toEqual([
            'inbox.outbox.col.document', 'inbox.outbox.col.participant', 'inbox.outbox.col.delivered', 'inbox.outbox.col.actions',
        ])
        expect(page.container.querySelectorAll('.doc-wide tbody tr td')).toHaveLength(4)
        page.unmount()
    })

    it('shows Status when a row is withdrawn or addressed to someone without an account', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'a', participant: 'p1' }),
            doc({ id: 'b', participant: 'p2', participant_name: 'Ben' }),
        ])
        const page = render()
        await settled(page, 'inbox.outbox.noAccount')

        expect(headers(page.container)).toContain('inbox.outbox.col.status')
        expect(page.container.querySelectorAll('.doc-wide tbody tr')[0]?.querySelectorAll('td')).toHaveLength(5)
        page.unmount()
    })

    it('lets the action buttons wrap in their cell and keeps inline styles out of the rows', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([doc({ id: 'a' })])
        const page = render()
        await settled(page, 'House rules')

        const actionsCell = page.container.querySelector('.doc-wide tbody td:last-child')
        expect(actionsCell?.classList.contains('doc-actions-col')).toBe(true)
        expect(page.container.querySelectorAll('.doc-wide tbody [style]')).toHaveLength(0)
        page.unmount()
    })

    it('shows one notice sent to several people as one row that opens to the addressees', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([
            doc({ id: 'a', participant: 'p1', participant_name: 'Anna', batch_id: 'b1' }),
            doc({ id: 'b', participant: 'p2', participant_name: 'Ben', batch_id: 'b1' }),
            doc({ id: 'c', participant: 'p1', participant_name: 'Anna', kind: 'invoice', title: 'OZV-1' }),
        ])
        const page = render()
        await settled(page, 'OZV-1')

        const rows = [...page.container.querySelectorAll('.doc-wide tbody tr')]
        expect(rows).toHaveLength(2)
        expect(rows[0].textContent).toContain('inbox.outbox.recipients')
        expect([...rows[0].querySelectorAll('.doc-recipients li')].map((item) => item.textContent)).toEqual([
            'Anna', expect.stringContaining('Ben'),
        ])
        expect(rows[1].textContent).toContain('Anna')
        page.unmount()
    })

    it('puts Withdraw in a menu and not beside Download, and offers none to a read-only role', async () => {
        vi.mocked(inboxApi.listInboxDocuments).mockResolvedValue([doc({ id: 'a' })])
        const page = render()
        await settled(page, 'House rules')

        const row = page.container.querySelector('.doc-wide tbody tr') as HTMLElement
        const labels = [...row.querySelectorAll('button')].map((button) => button.getAttribute('aria-label'))
        expect(labels).toEqual(['inbox.downloadLabel', 'inbox.outbox.moreActions'])
        expect(row.textContent).not.toContain('inbox.outbox.withdraw')
        page.unmount()

        canWrite = false
        const readOnly = render()
        await settled(readOnly, 'House rules')
        expect([...readOnly.container.querySelectorAll('.doc-wide tbody tr button')]).toHaveLength(1)
        readOnly.unmount()
    })
})
