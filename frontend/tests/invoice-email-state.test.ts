import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../src/lib/api/invoices', () => ({ openInvoicePdf: vi.fn() }))

import { InvoicePeriodRowsTable } from '../src/features/invoices/InvoicePeriodRowsTable'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach((cleanup) => cleanup()))

describe('invoice list email summary', () => {
    it('shows only the latest state and leaves delivery history to the Emails tab', () => {
        const container = document.createElement('div')
        document.body.appendChild(container)
        const root = createRoot(container)
        const rows = [{
            participant_id: 'p1',
            participant_name: 'Anna',
            participant_email: 'anna@example.com',
            metering_data_complete: true,
            metering_points_with_data: 1,
            metering_points_total: 1,
            missing_meter_ids: [],
            invoice: {
                id: 'i1',
                invoice_number: 'INV-1',
                status: 'sent',
                total_chf: '42.00',
                pdf_url: null,
                email_logs: [
                    { id: 'old', status: 'failed', created_at: '2026-01-01T10:00:00Z' },
                    { id: 'new', status: 'sent', created_at: '2026-01-01T11:00:00Z' },
                ],
            },
        }]
        act(() => root.render(createElement(
            MemoryRouter,
            null,
            createElement(InvoicePeriodRowsTable, {
                rows: rows as never,
                period: { period_start: '2026-01-01', period_end: '2026-01-31' },
                getPrimaryRowAction: () => null,
                getRowMenuItems: () => [],
                isPdfPending: () => false,
            }),
        )))
        cleanups.push(() => {
            act(() => root.unmount())
            container.remove()
        })

        const emailCell = container.querySelector('tbody tr')?.children.item(3)
        expect(emailCell?.textContent).toBe('email.sent')
        expect(emailCell?.querySelector('button, a')).toBeNull()
        expect(container.textContent).not.toContain('pages.invoices.viewLogs')
    })
})
