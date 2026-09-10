import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BillingPeriodCard } from '../src/components/BillingPeriodCard'
import { groupPeriodCards, primaryPeriodStep } from '../src/features/overview/periodCards'
import type { AttentionItem, ReadinessPeriod } from '../src/types/api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({
    t: (key: string, values?: { count?: number }) => `${key}${values?.count === undefined ? '' : `:${values.count}`}`,
    i18n: { resolvedLanguage: 'de' },
}) }))
vi.mock('../src/lib/appSettings', () => ({
    useAppSettings: () => ({ settings: {} }), formatShortDate: (value: string) => value,
}))

function period(start = '2026-06-01', end = '2026-06-30'): ReadinessPeriod {
    return { period: { start, end, interval: 'monthly', source: 'calendar', ended: true }, steps: [], next_action: 'none' }
}
function alert(type: AttentionItem['type'], id = type): AttentionItem {
    return { id, type, invoice_id: 'invoice-1', invoice_number: 'INV-1', label: 'DO NOT RENDER',
        period: { start: '2026-06-01', end: '2026-06-30' },
        link: '/billing/invoices?period_start=2026-06-01&period_end=2026-06-30' }
}
const cleanup: (() => void)[] = []
afterEach(() => cleanup.splice(0).forEach((fn) => fn()))
function render(entry: Parameters<typeof BillingPeriodCard>[0]['entry']) {
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    act(() => root.render(createElement(MemoryRouter, null, createElement(BillingPeriodCard, { entry }))))
    cleanup.push(() => { act(() => root.unmount()); container.remove() })
    return container
}

describe('Overview period cards', () => {
    it('merges alerts by both dates and restores historical periods absent from readiness', () => {
        const quarter = period('2026-06-01', '2026-08-31')
        const result = groupPeriodCards([quarter], [alert('invoice_overdue')])
        expect(result.open).toHaveLength(1)
        expect(result.open[0].period.end).toBe('2026-06-30')
        expect(result.completed[0].period.end).toBe('2026-08-31')
    })

    it('promotes an otherwise completed period when it has an alert', () => {
        const result = groupPeriodCards([period()], [alert('email_failed')])
        expect(result.open).toHaveLength(1)
        expect(result.completed).toHaveLength(0)
    })

    it('sorts open work oldest first without mutating query data', () => {
        const older = period(), newer = period('2026-08-01', '2026-08-31')
        older.steps = newer.steps = [{ key: 'approved', status: 'todo', count: 12 }]
        const input = [newer, older]
        expect(groupPeriodCards(input, []).open.map((entry) => entry.period.start)).toEqual(['2026-06-01', '2026-08-01'])
        expect(input[0]).toBe(newer)
    })

    it('does not turn running-period readiness warnings into work', () => {
        const current = period()
        current.period.ended = false
        current.steps = [{ key: 'metering', status: 'warn', count: 2, link: '/metering/quality' }]
        current.next_action = 'fix_metering'
        const result = groupPeriodCards([current], [])
        expect(result.open).toHaveLength(0)
        expect(result.current).toHaveLength(1)
        expect(primaryPeriodStep(result.current[0])).toBeUndefined()
    })

    it('keeps real invoice alerts visible on a running period without exposing readiness actions', () => {
        const current = period()
        current.period.ended = false
        current.steps = [{ key: 'metering', status: 'warn', count: 2, link: '/metering/quality' }]
        current.next_action = 'fix_metering'
        const result = groupPeriodCards([current], [alert('email_failed')])
        const container = render(result.open[0])
        expect(result.current).toHaveLength(0)
        expect(container.querySelector('a[href="/metering/quality"]')).toBeNull()
        expect(container.textContent).toContain('pages.overview.cards.failed:1')
    })

    it('retains periodless and participant notices independently of readiness', () => {
        const participant = alert('participant_validity')
        const periodless = { ...alert('invoice_overdue'), period: null }
        const result = groupPeriodCards([], [participant, periodless, alert('email_failed')])
        expect(result.community).toEqual([participant, periodless])
        expect(result.open).toHaveLength(1)
    })

    it('renders one invoice detail row for two issues, with both summaries visible and no English API fallback', () => {
        const entry = groupPeriodCards([period()], [alert('invoice_overdue'), alert('email_failed')]).open[0]
        const container = render(entry)
        expect(container.querySelectorAll('details li')).toHaveLength(1)
        expect(container.querySelector('.overview-period-work')?.textContent).toContain('pages.overview.cards.overdue:1')
        expect(container.querySelector('.overview-period-work')?.textContent).toContain('pages.overview.cards.failed:1')
        expect(container.textContent).not.toContain('DO NOT RENDER')
        expect(container.textContent).toContain('Juni')
        expect(container.textContent).not.toContain('→')
        expect(container.querySelector('details')?.open).toBe(false)
    })

    it('uses the backend-selected next action, not a different open step, and keeps other warnings visible', () => {
        const readiness = period()
        readiness.next_action = 'review_generation_conflicts'
        readiness.steps = [
            { key: 'metering', status: 'warn', count: 2, link: '/metering/quality' },
            { key: 'generation_conflicts', status: 'warn', count: 1, link: '/billing/invoices?period_start=2026-06-01&period_end=2026-06-30' },
            { key: 'approved', status: 'done', count: 0, link: '/unavailable' },
        ]
        const container = render(groupPeriodCards([readiness], []).open[0])
        expect(container.querySelector('.overview-period-card > a')?.textContent).toBe('pages.dashboard.cockpit.nextActionLabels.review_generation_conflicts')
        expect(container.querySelector('.overview-period-warning a')?.getAttribute('href')).toBe('/metering/quality')
        expect(container.querySelector('a[href="/unavailable"]')).toBeNull()
    })

    it('links every pending detail step even when their destinations are identical', () => {
        const readiness = period()
        const invoicesLink = '/billing/invoices?period_start=2026-06-01&period_end=2026-06-30'
        readiness.steps = [
            { key: 'sent', status: 'todo', count: 1, link: invoicesLink },
            { key: 'paid', status: 'todo', count: 3, total: 3, link: invoicesLink },
            { key: 'tariffs', status: 'ok', count: 0 },
            { key: 'assignments', status: 'done', count: 0 },
        ]
        const container = render(groupPeriodCards([readiness], []).open[0])
        const linkedSteps = [...container.querySelectorAll<HTMLAnchorElement>('.overview-step-link')]
        expect(linkedSteps.map((link) => link.textContent)).toEqual([
            'pages.dashboard.cockpit.stepLabels.sent',
            'pages.dashboard.cockpit.stepLabels.paid',
        ])
        expect(linkedSteps.every((link) => link.getAttribute('href') === invoicesLink)).toBe(true)
        expect(container.querySelectorAll('.overview-period-verified li')).toHaveLength(2)
    })

    it('does not double-count delivery failures reported by readiness and attention', () => {
        const readiness = period()
        readiness.next_action = 'send'
        readiness.steps = [{ key: 'sent', status: 'todo', count: 0, failed: 1, link: '/billing/invoices' }]
        const container = render(groupPeriodCards([readiness], [alert('email_failed')]).open[0])
        expect(container.querySelector('.overview-period-work')?.textContent).toContain('pages.overview.cards.failed:1')
        expect(container.textContent).not.toContain('stepDetails.emailFailedTodo')
    })
})
