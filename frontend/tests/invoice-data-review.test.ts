import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import type { Invoice } from '../src/types/api'

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

describe('InvoiceDataReviewNotice', () => {
    let container: HTMLDivElement
    let root: ReturnType<typeof createRoot>

    beforeEach(() => {
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
    })

    afterEach(() => {
        act(() => root.unmount())
        container.remove()
    })

    function render(inv: Invoice, variant: 'row' | 'detail', canAct: boolean) {
        act(() => {
            root.render(createElement(InvoiceDataReviewNotice, { invoice: inv, variant, canAct }))
        })
        return container.textContent ?? ''
    }

    it('renders nothing without an open impact', () => {
        expect(render(invoice({ needs_data_review: false }), 'row', true)).toBe('')
    })

    it('tells managers to regenerate a tainted draft', () => {
        const text = render(invoice({ status: 'draft', needs_data_review: true, open_data_impact_count: 2 }), 'row', true)
        expect(text).toContain('pages.invoices.dataReview.draftAction')
    })

    it('states facts without actions for read-only viewers', () => {
        const text = render(invoice({ status: 'draft', needs_data_review: true, open_data_impact_count: 1 }), 'row', false)
        expect(text).toContain('pages.invoices.dataReview.draftNotice')
        expect(text).not.toContain('pages.invoices.dataReview.draftAction')
    })

    it('routes issued invoices to cancel-then-regenerate, paid to persistence', () => {
        expect(render(invoice({ status: 'approved', needs_data_review: true, open_data_impact_count: 1 }), 'row', true))
            .toContain('pages.invoices.dataReview.issuedAction')
        expect(render(invoice({ status: 'sent', needs_data_review: true, open_data_impact_count: 1 }), 'row', false))
            .toContain('pages.invoices.dataReview.issuedNotice')
        expect(render(invoice({ status: 'paid', needs_data_review: true, open_data_impact_count: 1 }), 'row', true))
            .toContain('pages.invoices.dataReview.paidNotice')
    })

    it('lists source evidence on the detail variant', () => {
        const text = render(invoice({
            status: 'sent',
            needs_data_review: true,
            open_data_impact_count: 2,
            data_impacts: [
                {
                    id: 'imp-1',
                    import_log: 'log-1',
                    evidence: { source: 'sdat-import', delivery_id: 'DEL-1', change_count: 4, day_from: '2026-02-03', day_to: '2026-02-03' },
                    created_at: '2026-03-01T10:00:00Z',
                    resolution: '',
                    resolved_at: null,
                },
                {
                    id: 'imp-2',
                    import_log: null,
                    evidence: { source: 'import-deletion', deleted_readings: 9, day_from: '2026-02-04', day_to: '2026-02-05' },
                    created_at: '2026-03-02T10:00:00Z',
                    resolution: '',
                    resolved_at: null,
                },
            ],
        }), 'detail', true)
        expect(text).toContain('pages.invoices.dataReview.evidenceImport')
        expect(text).toContain('pages.invoices.dataReview.evidenceDeletion')
        expect(text).toContain('pages.invoices.dataReview.flaggedAt')
    })

    it('starts with 20 corrections and expands full detail history on request', () => {
        const impacts = Array.from({ length: 25 }, (_, i) => ({
            id: `impact-${i}`, import_log: null, evidence: { source: 'import-deletion', deleted_readings: 1 },
            created_at: '2026-03-01T10:00:00Z', resolution: '', resolved_at: null,
        }))
        render(invoice({ needs_data_review: true, open_data_impact_count: 25, data_impacts: impacts }), 'detail', true)
        expect(container.querySelectorAll('li')).toHaveLength(20)
        act(() => container.querySelector('button')!.click())
        expect(container.querySelectorAll('li')).toHaveLength(25)
        act(() => container.querySelector('button')!.click())
        expect(container.querySelectorAll('li')).toHaveLength(20)
    })

    it('shows no evidence list on the row variant', () => {
        const text = render(invoice({
            status: 'sent',
            needs_data_review: true,
            open_data_impact_count: 1,
            data_impacts: [
                {
                    id: 'imp-1',
                    import_log: 'log-1',
                    evidence: { source: 'sdat-import', delivery_id: 'DEL-1' },
                    created_at: '2026-03-01T10:00:00Z',
                    resolution: '',
                    resolved_at: null,
                },
            ],
        }), 'row', true)
        expect(text).not.toContain('pages.invoices.dataReview.evidenceImport')
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
