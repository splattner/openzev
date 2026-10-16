import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Invoice, InvoicePeriodParticipantRow } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/invoices', () => ({ openInvoicePdf: vi.fn() }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }),
    formatShortDate: (value: string) => value,
}))

import { InvoicePeriodRowsTable } from '../src/features/invoices/InvoicePeriodRowsTable'

const invoice: Invoice = {
    id: 'i1', invoice_number: 'INV-1', zev: 'z1', zev_name: 'Community A', participant: 'p1', participant_name: 'Anna',
    period_start: '2026-02-01', period_end: '2026-02-28', status: 'sent', total_chf: '12.30',
    pdf_url: '/stored.pdf', pdf_status: 'ready', last_email_status: 'sent',
}
const base: InvoicePeriodParticipantRow = {
    participant_id: 'p1', participant_name: 'Anna', participant_email: 'anna@example.com',
    participant_kind: 'person', participant_name_addition: '', participant_valid_from: '2026-01-01',
    participant_valid_to: null, party_id: 'party-1', metering_point_labels: [],
    metering_data_complete: true, metering_points_total: 1, metering_points_with_data: 1,
    missing_meter_ids: [], generation_eligibility: null, invoice: { ...invoice },
}

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))
beforeEach(() => vi.clearAllMocks())

function mount(rows: InvoicePeriodParticipantRow[], overrides: Partial<Parameters<typeof InvoicePeriodRowsTable>[0]> = {}) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    function Location() {
        const location = useLocation()
        return createElement('output', null, JSON.stringify(location.state))
    }
    act(() => root.render(createElement(MemoryRouter, null, createElement(MantineProvider, null,
        createElement(InvoicePeriodRowsTable, {
            rows,
            period: { period_start: '2026-02-01', period_end: '2026-02-28' },
            getPrimaryRowAction: () => null,
            getRowMenuItems: () => [],
            getRowWork: () => ({}),
            repeatedPartyIds: new Set<string>(),
            ...overrides,
        }),
    ), createElement(Location))))
    cleanups.push(() => { act(() => root.unmount()); container.remove() })
    return { container }
}

const rowsOf = (container: HTMLElement) => [...container.querySelectorAll<HTMLTableRowElement>('tbody tr')]
const occurrences = (text: string, needle: string) => text.split(needle).length - 1
const stepStates = (row: HTMLElement) => Object.fromEntries([...row.querySelectorAll<HTMLElement>('[data-step]')]
    .map((step) => [step.dataset.step, step.dataset.state]))

describe('invoice period row layout', () => {
    it('states the four columns the page keeps', () => {
        const { container } = mount([base])
        expect([...container.querySelectorAll('thead th')].map((th) => th.textContent)).toEqual([
            'pages.invoices.col.participant',
            'pages.invoices.col.progress',
            'pages.invoices.col.amount',
            'pages.invoices.col.actions',
        ])
        expect(rowsOf(container)[0].children).toHaveLength(4)
        // The header names the currency, so amounts read as plain numbers;
        // the card layout, which hides the header, shows it inline.
        expect(rowsOf(container)[0].children[2].querySelector('.invoice-row-currency')?.textContent).toBe('CHF ')
        expect(rowsOf(container)[0].children[2].textContent).toBe('CHF 12.30')
        // The legend explains the step icons once, below the rows.
        expect(container.querySelector('.invoice-progress-legend')?.textContent).toContain('pages.invoices.progress.steps.metering')
        expect(container.querySelector('.invoice-rows .invoice-progress-legend')).toBeNull()
    })

    it('puts the invoice number in the identity cell as the row\'s only detail link', async () => {
        const { container } = mount([{ ...base, generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null } }])
        const row = rowsOf(container)[0]
        const identity = row.children[0]
        expect(identity.textContent).toContain('Anna')
        // The address is the participant page's business, not the billing row's.
        expect(identity.textContent).not.toContain('anna@example.com')
        expect(identity.textContent).toContain('INV-1')

        // One link, in the identity cell: no second "Open details" affordance.
        const links = [...row.querySelectorAll('a')]
        expect(links).toHaveLength(1)
        expect(links[0].getAttribute('href')).toBe('/billing/invoices/i1')
        expect(row.children[1].querySelector('a, button')).toBeNull()
        expect(container.textContent).not.toContain('pages.invoices.openDetails')

        // The return path stays with the link.
        await act(async () => links[0].click())
        expect(JSON.parse(container.querySelector('output')!.textContent!)).toEqual({
            from: '/billing/invoices', period_start: '2026-02-01', period_end: '2026-02-28',
        })
    })

    it('shows each workflow step and every problem without losing a state', () => {
        const { container } = mount([
            base,
            { ...base, participant_id: 'p2', invoice: { ...invoice, id: 'i2', status: 'draft', pdf_url: null, pdf_status: 'failed', last_email_status: null } },
            { ...base, participant_id: 'p3', invoice: { ...invoice, id: 'i3', status: 'approved', pdf_url: null, pdf_status: 'pending', last_email_status: 'failed' } },
            { ...base, participant_id: 'p4', invoice: null },
        ])
        const [sent, draft, approved, none] = rowsOf(container)

        expect(stepStates(sent)).toEqual({ metering: 'done', invoice: 'done', approved: 'done', sent: 'done', paid: 'open' })
        // The PDF opens from the row menu: the identity cell links the invoice only.
        expect(sent.children[0].querySelector('button')).toBeNull()
        expect(sent.querySelector('.invoice-row-issues')).toBeNull()

        // A failed render without a document is a problem on the invoice step.
        expect(stepStates(draft)).toEqual({ metering: 'done', invoice: 'issue', approved: 'open', sent: 'open', paid: 'open' })
        expect(draft.querySelector('.invoice-row-issues')?.textContent).toBe('pages.invoices.issues.pdf')
        // A step in trouble says what the trouble is, not only that there is one.
        expect(draft.querySelector('[data-step="invoice"]')?.getAttribute('title')).toBe('pages.invoices.issues.pdf')

        expect(stepStates(approved)).toMatchObject({ invoice: 'active', sent: 'issue' })
        expect(approved.querySelector('[data-step="invoice"]')?.getAttribute('title')).toBe('pages.invoices.progress.reasons.pdfPending')
        expect(approved.querySelector('[data-step="sent"]')?.getAttribute('title')).toBe('pages.invoices.issues.delivery')
        expect(approved.querySelector('.invoice-row-issues')?.textContent).toBe('pages.invoices.issues.delivery')
        // A step without trouble says what it means for the row.
        expect(sent.querySelector('[data-step="invoice"]')?.getAttribute('title')).toBe('pages.invoices.progress.done.invoice')
        expect(sent.querySelector('[data-step="paid"]')?.getAttribute('title')).toBe('pages.invoices.progress.open.paid')

        // Each step names itself and its state for assistive technology.
        expect(sent.querySelector('ol')?.getAttribute('aria-label')).toBe('pages.invoices.progress.label')
        expect(sent.querySelectorAll('ol .visually-hidden')).toHaveLength(5)

        expect(stepStates(none).invoice).toBe('open')
        expect(none.children[2].textContent).toBe('-')
    })

    it('reports a row\'s own render as pending rather than failed', () => {
        const failed = { ...base, invoice: { ...invoice, status: 'draft', pdf_url: null, pdf_status: 'failed' as const } }
        const { container } = mount([failed], { getRowWork: () => ({ pdfPending: true }) })
        const row = rowsOf(container)[0]
        expect(stepStates(row).invoice).toBe('active')
        expect(row.querySelector('.invoice-row-issues')).toBeNull()
    })

    it('shows an invoice in the making on the row and on its invoice step', () => {
        const { container } = mount([{ ...base, invoice: null }], { getRowWork: () => ({ generating: true }) })
        const row = rowsOf(container)[0]
        expect(row.children[0].querySelector('.invoice-row-pending')?.textContent).toBe('pages.invoices.progress.reasons.generating')
        expect(row.children[0].textContent).not.toContain('pages.invoices.notCreated')
        expect(stepStates(row).invoice).toBe('active')
    })

    it('names whom a row bills: an organisation, a household, a move, a second participation', () => {
        const { container } = mount([
            {
                ...base, participant_kind: 'organisation', participant_name_addition: 'c/o Buchhaltung',
                participant_valid_from: '2026-02-10', participant_valid_to: null, party_id: 'party-1',
                metering_point_labels: ['Flat 2'],
            },
            {
                ...base, participant_id: 'p2', participant_valid_from: '2025-01-01', participant_valid_to: '2026-02-20',
                party_id: 'party-2', metering_point_labels: ['Flat 3'],
            },
        ], { repeatedPartyIds: new Set(['party-1']) })
        const [organisation, person] = rowsOf(container).map((row) => row.children[0])
        expect(organisation.querySelector('.invoice-row-kind')).not.toBeNull()
        expect(organisation.textContent).toContain('c/o Buchhaltung')
        expect(organisation.textContent).toContain('pages.invoices.row.joined')
        // Meter locations appear only where one party has several rows.
        expect(organisation.textContent).toContain('Flat 2')
        expect(person.querySelector('.invoice-row-kind')).toBeNull()
        expect(person.textContent).toContain('pages.invoices.row.left')
        expect(person.textContent).not.toContain('pages.invoices.row.joined')
        expect(person.textContent).not.toContain('Flat 3')
    })

    it('renders the states that have no invoice once each', () => {
        const { container } = mount([
            { ...base, participant_id: 'p2', invoice: null },
            { ...base, participant_id: 'p3', invoice: null, generation_eligibility: { state: 'covered', invoice_id: 'old', invoice_number: 'OLD' } },
        ])
        const [notCreated, covered] = rowsOf(container).map((row) => row.textContent!)
        expect(occurrences(notCreated, 'pages.invoices.notCreated')).toBe(1)
        expect(occurrences(covered, 'pages.invoices.covered.label')).toBe(1)
        expect(covered).not.toContain('pages.invoices.notCreated')
        // An already billed row has no workflow of its own: it links the
        // invoice that bills it, keeping the way back.
        const coveredRow = rowsOf(container)[1]
        expect(coveredRow.querySelector('[data-step]')).toBeNull()
        expect(coveredRow.querySelector('.invoice-progress-covered a')?.getAttribute('href')).toBe('/billing/invoices/old')
        expect(coveredRow.querySelector('.invoice-progress-covered a')?.textContent).toBe('OLD')
    })

    it('keeps a cancelled invoice reachable without billing its amount', () => {
        const { container } = mount([{
            ...base, invoice: { ...invoice, status: 'cancelled' },
            generation_eligibility: { state: 'eligible', invoice_id: null, invoice_number: null },
        }])
        const row = rowsOf(container)[0]
        expect(row.children[0].textContent).toContain('INV-1 (invoice.status.cancelled)')
        expect(stepStates(row).invoice).toBe('open')
        expect(row.children[2].textContent).toBe('-')
    })

    it('names the cancelled invoice the current one replaces, and links to it', () => {
        const { container } = mount([{
            ...base,
            invoice: { ...invoice, replaces: [{ id: 'i0', invoice_number: 'INV-0' }, { id: 'i00', invoice_number: 'INV-00' }] },
        }])
        const identity = rowsOf(container)[0].children[0]
        expect(identity.textContent).toContain('pages.invoices.row.replaces INV-0 (invoice.status.cancelled) pages.invoices.row.moreReplaced')
        expect([...identity.querySelectorAll('a')].map((a) => a.getAttribute('href')))
            .toEqual(['/billing/invoices/i1', '/billing/invoices/i0'])
    })

    it('says nothing about replacement when nothing was replaced', () => {
        const { container } = mount([{ ...base, invoice: { ...invoice, replaces: [] } }])
        expect(container.textContent).not.toContain('pages.invoices.row.replaces')
    })

    it('keeps ineligible, incomplete metering and blocked rows visible', () => {
        const { container } = mount([
            {
                ...base, participant_id: 'p2', invoice: null,
                metering_data_complete: false, metering_points_with_data: 1, missing_meter_ids: ['CH-1'],
                missing_meter_details: [{ meter_id: 'CH-1', missing_days: 2 }],
                generation_eligibility: { state: 'blocked', invoice_id: 'overlap', invoice_number: 'OLD-9' },
            },
        ])
        const row = rowsOf(container)[0]
        expect(row.children[0].textContent).toContain('pages.invoices.notCreated')
        expect([...row.querySelectorAll('.invoice-row-issues > span')].map((issue) => issue.textContent)).toEqual([
            'pages.invoices.issues.metering', 'pages.invoices.issues.conflict',
        ])
        expect(row.children[0].textContent).toContain('CH-1 (pages.invoices.metering.missingDays)')
        expect(stepStates(row)).toMatchObject({ metering: 'issue', invoice: 'issue' })
    })

    it('outlines the row action so the batch action stays the one primary button', () => {
        const { container } = mount([base], {
            getPrimaryRowAction: () => ({ key: 'mark-paid', label: 'Mark paid', onClick: vi.fn() }),
        })
        const button = rowsOf(container)[0].querySelector<HTMLButtonElement>('.invoice-actions-cell button')!
        expect(button.textContent).toBe('Mark paid')
        expect(button.className).toContain('button-secondary')
        expect(button.className).not.toContain('button-primary')
    })
})
