import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import type { Invoice, InvoiceReadingImpact } from '../src/types/api'

const authState = vi.hoisted(() => ({
    user: {
        role: 'manager',
        memberships: [{ zev: 'zev-1', access: 'manager', participants: [] }],
    } as { role: string; memberships: Array<{ zev: string; access?: string; participants: Array<{ id: string; live: boolean }> }> },
}))
const selectedScope = vi.hoisted(() => ({ relation: 'manager' as 'manager' | 'viewer' | 'participant' | 'former' | undefined }))

vi.mock('../src/lib/auth', () => ({ useAuth: () => ({ user: authState.user }) }))
vi.mock('../src/lib/managedZev', () => ({ useOptionalManagedZev: () => ({ selectedZevId: 'zev-2', relation: selectedScope.relation }) }))

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('../src/lib/appSettings', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../src/lib/appSettings')>()
    return {
        ...actual,
        useAppSettings: () => ({ settings: {} }),
        formatShortDate: (value: string) => value,
    }
})

import { InvoiceDataReviewNotice } from '../src/features/invoices/InvoiceDataReviewNotice'
import { NEXT_ACTION_STEP_KEYS, stepDetailText } from '../src/features/overview/readinessPresentation'
import type { ReadinessStep } from '../src/types/api'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

function invoice(overrides: Partial<Invoice> = {}): Invoice {
    return {
        id: 'inv-1',
        invoice_number: 'INV-1',
        zev: 'zev-1',
        zev_name: 'ZEV 1',
        participant: 'p-1',
        participant_name: 'Anna',
        period_start: '2026-02-01',
        period_end: '2026-02-28',
        total_chf: '10.00',
        status: 'draft',
        ...overrides,
    }
}

function impact(overrides: Partial<InvoiceReadingImpact> = {}): InvoiceReadingImpact {
    return {
        id: 'imp-1', import_log: 'log-1',
        evidence: { source: 'sdat-import', delivery_id: 'DEL-1', change_count: 4, day_from: '2026-02-03', day_to: '2026-02-04' },
        created_at: '2026-03-01T10:00:00Z', resolution: '', resolved_at: null,
        ...overrides,
    }
}

describe('InvoiceDataReviewNotice', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(() => {
        selectedScope.relation = 'manager'
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
        authState.user = {
            role: 'manager',
            memberships: [{ zev: 'zev-1', access: 'manager', participants: [] }],
        }
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    function render(inv: Invoice, canAct: boolean) {
        act(() => {
            root.render(
                createElement(
                    MemoryRouter,
                    null,
                    createElement(InvoiceDataReviewNotice, {
                        invoice: inv,
                        canAct,
                    }),
                ),
            )
        })
        return container.textContent ?? ''
    }

    it('renders nothing without an open impact', () => {
        expect(render(invoice({ needs_data_review: false }), true)).toBe('')
    })

    it('tells managers to regenerate a tainted draft', () => {
        const text = render(invoice({ status: 'draft', needs_data_review: true, open_data_impact_count: 2 }), true)
        expect(text).toContain('pages.invoices.dataReview.draftAction')
    })

    it('states facts without actions for read-only viewers', () => {
        const text = render(invoice({ status: 'draft', needs_data_review: true, open_data_impact_count: 1 }), false)
        expect(text).toContain('pages.invoices.dataReview.draftNotice')
        expect(text).not.toContain('pages.invoices.dataReview.draftAction')
    })

    it('explains the review according to invoice status', () => {
        expect(render(invoice({ status: 'approved', needs_data_review: true, open_data_impact_count: 1 }), true))
            .toContain('pages.invoices.dataReview.issuedAction')
        expect(render(invoice({ status: 'sent', needs_data_review: true, open_data_impact_count: 1 }), false))
            .toContain('pages.invoices.dataReview.issuedNotice')
        expect(render(invoice({ status: 'paid', needs_data_review: true, open_data_impact_count: 1 }), true))
            .toContain('pages.invoices.dataReview.paidNotice')
    })


    it('lists source evidence on the detail variant', () => {
        const text = render(invoice({
            status: 'sent',
            needs_data_review: true,
            open_data_impact_count: 2,
            data_impacts: [
                impact({ evidence: { source: 'sdat-import', delivery_id: 'DEL-1', change_count: 4, day_from: '2026-02-03', day_to: '2026-02-03' } }),
                impact({ id: 'imp-2', import_log: null, evidence: { source: 'import-deletion', deleted_readings: 9, day_from: '2026-02-04', day_to: '2026-02-05' }, created_at: '2026-03-02T10:00:00Z' }),
            ],
        }), true)
        expect(text).toContain('pages.invoices.dataReview.evidenceImport')
        expect(text).toContain('pages.invoices.dataReview.evidenceDeletion')
        expect(text).toContain('pages.invoices.dataReview.flaggedAt')
    })

    it('shows a single correction as a paragraph with a visible link indicator', () => {
        render(invoice({ needs_data_review: true, data_impacts: [impact()] }), true)
        expect(container.querySelector('ul, li')).toBeNull()
        expect(container.querySelector('a [aria-hidden="true"]')?.textContent).toBe('→')
    })

    it('starts with 20 corrections and expands full detail history on request', () => {
        const impacts = Array.from({ length: 25 }, (_, i) => ({
            id: `impact-${i}`, import_log: null, evidence: { source: 'import-deletion', deleted_readings: 1 },
            created_at: '2026-03-01T10:00:00Z', resolution: '', resolved_at: null,
        }))
        render(invoice({ needs_data_review: true, open_data_impact_count: 25, data_impacts: impacts }), true)
        expect(container.querySelectorAll('p.m-0')).toHaveLength(21)
        act(() => container.querySelector('button')!.click())
        expect(container.querySelectorAll('p.m-0')).toHaveLength(26)
        act(() => container.querySelector('button')!.click())
        expect(container.querySelectorAll('p.m-0')).toHaveLength(21)
    })

    it('links a manager to the import behind the flagged changes', () => {
        render(invoice({
            status: 'draft',
            needs_data_review: true,
            open_data_impact_count: 1,
            data_impacts: [impact()],
        }), true)

        const link = container.querySelector('a')
        expect(link?.textContent).toBe('pages.invoices.dataReview.openImport→')
        const href = link?.getAttribute('href') ?? ''
        expect(href).toBe('/metering/imports?import=log-1&change_from=2026-02-03&change_to=2026-02-04#correction-history')
    })

    it.each(['participant', 'former', undefined] as const)('hides an unreachable import link in %s scope', (relation) => {
        selectedScope.relation = relation
        render(invoice({ needs_data_review: true, data_impacts: [impact()] }), true)
        expect(container.querySelector('a')).toBeNull()
        expect(container.textContent).toContain('pages.invoices.dataReview.evidenceImport')
    })

    it.each(['manager', 'viewer'] as const)('keeps cross-community evidence reachable in %s scope', (relation) => {
        selectedScope.relation = relation
        render(invoice({ needs_data_review: true, data_impacts: [impact()] }), false)
        expect(container.querySelector('a')?.getAttribute('href')).toContain('import=log-1')
    })

    it('offers no import link to a participant holding the invoice', () => {
        // Participants already receive no impacts; the link must not appear even
        // if such a row reaches the client.
        authState.user = {
            role: 'user',
            memberships: [{ zev: 'zev-1', participants: [{ id: 'p-1', live: true }] }],
        }
        render(invoice({
            status: 'sent',
            needs_data_review: true,
            open_data_impact_count: 1,
            data_impacts: [impact()],
        }), false)

        expect(container.querySelector('a')).toBeNull()
        expect(container.textContent).toContain('pages.invoices.dataReview.evidenceImport')
    })

    it.each(['viewer', 'admin'])('links a %s without requiring invoice write access', (role) => {
        authState.user = { role: role === 'admin' ? 'admin' : 'user', memberships: [
            { zev: 'zev-1', access: role, participants: [] },
        ] }
        render(invoice({ needs_data_review: true, data_impacts: [impact({ id: 'imp', import_log: 'log/1', evidence: {}, created_at: '2026-03-01' })] }), false)
        expect(container.querySelector('a')?.getAttribute('href')).toBe('/metering/imports?import=log%2F1#correction-history')
    })

    it('does not offer a link based on access to another community', () => {
        render(invoice({ zev: 'zev-other', needs_data_review: true, data_impacts: [impact({ id: 'imp', import_log: 'foreign', evidence: {}, created_at: '2026-03-01' })] }), true)
        expect(container.querySelector('a')).toBeNull()
    })

    it('offers no import link when the impact has no source import', () => {
        render(invoice({
            status: 'draft',
            needs_data_review: true,
            open_data_impact_count: 1,
            data_impacts: [impact({ id: 'imp-2', import_log: null, evidence: { source: 'import-deletion', deleted_readings: 9, day_from: '2026-02-04', day_to: '2026-02-04' }, created_at: '2026-03-02T10:00:00Z' })],
        }), true)

        expect(container.querySelector('a')).toBeNull()
    })

})

describe('readiness data_corrections step', () => {
    const t = vi.fn((key: string) => key) as never

    it('maps the review_data_corrections action back to its step', () => {
        expect(NEXT_ACTION_STEP_KEYS.review_data_corrections).toEqual(['data_corrections'])
    })

    it('summarizes tainted invoices from structured detail data', () => {
        const step: ReadinessStep = {
            key: 'data_corrections',
            status: 'warn',
            count: 2,
            detail_data: {
                correction_count: 5,
                corrections: [
                    { invoice_id: 'i1', invoice_number: 'INV-1', participant_name: 'Anna', status: 'draft', delivery_id: 'DEL-1', flagged_at: '2026-03-01', correction_count: 1 },
                    { invoice_id: 'i2', invoice_number: 'INV-2', participant_name: 'Ben', status: 'sent', delivery_id: 'DEL-2', flagged_at: '2026-03-01', correction_count: 1 },
                ],
                more_corrections: 0,
            },
            link: '/billing/invoices?period_start=2026-02-01&period_end=2026-02-28',
        }
        expect(stepDetailText(step, t)).toBe('pages.dashboard.cockpit.stepDetails.correctionsWarn')
        expect(t).toHaveBeenCalledWith('pages.dashboard.cockpit.stepDetails.correctionsWarn', { count: 2, invoices: 'INV-1, INV-2' })
    })

    it('stays silent unless the step warns', () => {
        expect(stepDetailText({ key: 'data_corrections', status: 'ok', count: 0 }, t)).toBeNull()
    })
})
