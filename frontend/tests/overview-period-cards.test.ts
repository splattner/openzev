import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BillingPeriodCard } from '../src/components/BillingPeriodCard'
import { groupPeriodCards, primaryPeriodStep } from '../src/features/overview/periodCards'
import type { AttentionItem, ReadinessPeriod, ReadinessStep } from '../src/types/api'

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
    it.each<[ReadinessStep['key'], ReadinessStep['status'], string, ReadinessPeriod['next_action']]>([
        ['data_corrections', 'warn', 'caution', 'review_data_corrections'],
        ['metering', 'warn', 'caution', 'fix_metering'],
        ['charges', 'todo', 'caution', 'generate'],
        ['charges', 'warn', 'caution', 'generate'],
        ['assignments', 'warn', 'issue', 'fix_assignments'],
        ['tariffs', 'warn', 'issue', 'fix_tariffs'],
        ['tariffs', 'todo', 'issue', 'fix_tariffs'],
        ['generation_conflicts', 'warn', 'issue', 'review_generation_conflicts'],
    ])('applies severity to primary and non-primary %s steps (%s)', (key, status, tone, action) => {
        const readiness = period()
        const step: ReadinessStep = { key, status, count: 2, link: '/fix' }
        readiness.steps = [step]
        readiness.next_action = action
        const primary = render({ period: readiness.period, readiness, alerts: [] })
        expect(primary.querySelector(`.overview-period-lead.overview-period-${tone}`)).not.toBeNull()
        expect(primary.querySelector('.overview-period-card > a')?.classList.contains(
            status === 'warn' ? 'button-secondary' : 'button-primary',
        )).toBe(true)
        readiness.next_action = 'none'
        const secondary = render({ period: readiness.period, readiness, alerts: [] })
        expect(secondary.querySelector(status === 'warn'
            ? `.overview-period-warning.overview-period-${tone} a[href="/fix"]`
            : `.overview-period-pending .overview-period-${tone}`)).not.toBeNull()
    })

    it.each<[ReadinessStep['key'], ReadinessPeriod['next_action']]>([
        ['generated', 'generate'],
        ['approved', 'approve'],
        ['sent', 'send'],
        ['paid', 'track_payments'],
    ])('leaves the routine %s step neutral as the primary action', (key, action) => {
        const readiness = period()
        readiness.steps = [{ key, status: 'todo', count: 1, total: 2, link: '/billing/invoices' }]
        readiness.next_action = action
        const container = render({ period: readiness.period, readiness, alerts: [] })
        expect(container.querySelector('.overview-period-lead')).not.toBeNull()
        expect(container.querySelector('.overview-period-issue, .overview-period-caution')).toBeNull()
        expect(container.querySelector('.overview-period-card > a')?.classList.contains('button-primary')).toBe(true)
    })

    it.each<[ReadinessStep['key'], ReadinessStep['status']]>([
        ['generated', 'todo'],
        ['approved', 'todo'],
        ['sent', 'todo'],
        ['paid', 'todo'],
        ['approved', 'done'],
        ['metering', 'ok'],
        ['tariffs', 'ok'],
        ['charges', 'done'],
    ])('leaves the routine or resolved %s step (%s) neutral in the disclosure', (key, status) => {
        const readiness = period()
        readiness.steps = [{ key, status, count: 1, total: 2 }]
        readiness.next_action = 'none'
        const container = render({ period: readiness.period, readiness, alerts: [] })
        expect(container.textContent).toContain(`pages.dashboard.cockpit.stepLabels.${key}`)
        expect(container.querySelector('.overview-period-issue, .overview-period-caution')).toBeNull()
    })

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

    it('takes the stale-charges step as the primary one when generation itself is done', () => {
        const stale = period()
        stale.steps = [
            { key: 'generated', status: 'done', count: 3, total: 3 },
            { key: 'charges', status: 'todo', count: 1, detail_data: { stale_drafts: 1 } },
        ]
        stale.next_action = 'generate'
        expect(primaryPeriodStep(groupPeriodCards([stale], []).open[0])?.key).toBe('charges')
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
        expect(container.querySelector('.overview-period-caution')?.textContent).toContain('pages.overview.cards.overdue:1')
        expect(container.querySelector('.overview-period-issue')?.textContent).toContain('pages.overview.cards.failed:1')
        expect(container.querySelectorAll('.overview-period-pending .muted')).toHaveLength(2)
        expect(container.querySelector('.overview-period-card > a')?.classList.contains('button-secondary')).toBe(true)
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
        expect(container.querySelector('.overview-period-lead.overview-period-issue')?.textContent).toContain('stepDetails.conflictsWarn')
        const warning = container.querySelector('a[href="/metering/quality"]')!
        expect(warning.textContent).toContain('stepDetails.meteringWarn')
        expect(warning.closest('p')?.classList.contains('overview-period-caution')).toBe(true)
        expect(container.querySelector('a[href="/unavailable"]')).toBeNull()
    })

    it('keeps pending links and completed checks in independent disclosures', () => {
        const readiness = period()
        readiness.next_action = 'generate'
        const invoicesLink = '/billing/invoices?period_start=2026-06-01&period_end=2026-06-30'
        readiness.steps = [
            { key: 'generated', status: 'todo', count: 0, total: 1, link: invoicesLink },
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
        const pending = container.querySelector<HTMLDetailsElement>('details:not(.overview-period-verified)')!
        const verified = container.querySelector<HTMLDetailsElement>('.overview-period-verified')!
        expect(pending.querySelector('summary')?.textContent).toBe('pages.overview.cards.details')
        expect(verified.querySelector('summary')?.textContent).toBe('pages.overview.cards.verified')
        expect(pending.parentElement).toBe(verified.parentElement)
        expect(pending.textContent).not.toContain('pages.dashboard.cockpit.stepLabels.tariffs')
        expect(verified.textContent).not.toContain('pages.dashboard.cockpit.stepLabels.sent')
        expect(pending.open).toBe(false)
        expect(verified.open).toBe(false)
        act(() => verified.querySelector('summary')!.click())
        expect(verified.open).toBe(true)
        expect(pending.open).toBe(false)
        act(() => pending.querySelector('summary')!.click())
        expect(pending.open).toBe(true)
        expect(verified.open).toBe(true)
    })

    it('does not double-count delivery failures reported by readiness and attention', () => {
        const readiness = period()
        readiness.next_action = 'send'
        readiness.steps = [{ key: 'sent', status: 'todo', count: 0, failed: 1, link: '/billing/invoices' }]
        const container = render(groupPeriodCards([readiness], [alert('email_failed')]).open[0])
        expect(container.querySelector('.overview-period-work')?.textContent).toContain('pages.overview.cards.failed:1')
        expect(container.textContent).not.toContain('stepDetails.emailFailedTodo')
    })

    it('shows collapsed completed checks without pending details and omits zero-count charges', () => {
        const readiness = period()
        readiness.next_action = 'generate'
        readiness.steps = [
            { key: 'generated', status: 'todo', count: 1, link: '/billing/invoices' },
            { key: 'metering', status: 'ok', count: 1 },
            { key: 'charges', status: 'ok', count: 0 },
        ]
        const container = render(groupPeriodCards([readiness], []).open[0])
        const verified = container.querySelector<HTMLDetailsElement>('.overview-period-verified')
        expect(verified?.querySelectorAll('li')).toHaveLength(1)
        expect(verified?.open).toBe(false)
        expect(verified?.querySelector('summary')?.textContent).toBe('pages.overview.cards.verified')
        expect(container.querySelectorAll('details')).toHaveLength(1)
        act(() => verified?.querySelector('summary')?.click())
        expect(verified?.open).toBe(true)
        expect(verified?.textContent).toContain('pages.dashboard.cockpit.stepLabels.metering')
    })

    it('retains every completed check when no primary or pending work remains', () => {
        const readiness = period()
        readiness.steps = [
            { key: 'generated', status: 'done', count: 1, total: 1 },
            { key: 'charges', status: 'done', count: 2 },
        ]
        const entry = groupPeriodCards([readiness], []).completed[0]
        expect(primaryPeriodStep(entry)).toBeUndefined()
        const container = render(entry)
        const verified = container.querySelector<HTMLDetailsElement>('.overview-period-verified')!
        expect(verified.open).toBe(false)
        expect(container.querySelectorAll('details')).toHaveLength(1)
        expect([...verified.querySelectorAll('li > span:last-child')].map((item) => item.textContent)).toEqual([
            'pages.dashboard.cockpit.stepLabels.generated',
            'pages.dashboard.cockpit.stepLabels.charges',
        ])
    })

    it('keeps a zero-count charge actionable when a draft needs regeneration', () => {
        const readiness = period()
        readiness.next_action = 'generate'
        readiness.steps = [{ key: 'charges', status: 'todo', count: 0,
            detail_data: { stale_drafts: 1 }, link: '/billing/invoices' }]
        const entry = groupPeriodCards([readiness], []).open[0]
        expect(primaryPeriodStep(entry)?.key).toBe('charges')
        const container = render(entry)
        expect(container.querySelector('.overview-period-card > a')?.getAttribute('href')).toBe('/billing/invoices')
        expect(container.querySelector('.overview-period-work')?.textContent).toContain('stepDetails.chargesTodo:1')
        expect(container.querySelector('.overview-period-verified')).toBeNull()
    })
})
