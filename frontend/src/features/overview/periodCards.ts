import type { AttentionItem, ReadinessPeriod, ReadinessStep } from '../../types/api'
import { NEXT_ACTION_STEP_KEY } from './readinessPresentation'

export interface PeriodCardEntry {
    period: ReadinessPeriod['period']
    readiness?: ReadinessPeriod
    alerts: AttentionItem[]
}

export const periodKey = (period: { start: string; end: string }) => `${period.start}/${period.end}`
export const isOpenStep = (step: ReadinessStep) => step.status === 'warn' || step.status === 'todo'

/** Merge on BOTH dates, including old invoice periods outside readiness history.
 * Non-period alerts remain independent, even when readiness fails to load. */
export function groupPeriodCards(periods: ReadinessPeriod[], alerts: AttentionItem[]) {
    const entries = new Map<string, PeriodCardEntry>()
    for (const readiness of periods) {
        if (!readiness.period) continue
        entries.set(periodKey(readiness.period), { period: readiness.period, readiness, alerts: [] })
    }
    const community: AttentionItem[] = []
    for (const alert of alerts) {
        if (!alert.period || alert.type === 'participant_validity') {
            community.push(alert)
            continue
        }
        const key = periodKey(alert.period)
        let entry = entries.get(key)
        if (!entry) {
            entry = {
                period: { ...alert.period, interval: null, source: 'invoice', ended: true },
                alerts: [],
            }
            entries.set(key, entry)
        }
        entry.alerts.push(alert)
    }
    const ordered = [...entries.values()].sort((a, b) =>
        a.period.start.localeCompare(b.period.start) || a.period.end.localeCompare(b.period.end),
    )
    return {
        open: ordered.filter((entry) => entry.alerts.length > 0 || (
            entry.period.ended !== false && entry.readiness?.steps.some(isOpenStep)
        )),
        current: ordered.filter((entry) => entry.period.ended === false && entry.alerts.length === 0),
        completed: ordered.filter((entry) => entry.period.ended !== false && entry.alerts.length === 0
            && entry.readiness && !entry.readiness.steps.some(isOpenStep)),
        community,
    }
}

export function primaryPeriodStep(entry: PeriodCardEntry) {
    if (entry.period.ended === false || !entry.readiness) return undefined
    const key = NEXT_ACTION_STEP_KEY[entry.readiness.next_action]
    return entry.readiness.steps.find((step) => step.key === key && isOpenStep(step))
}

/** One detail row per invoice, even if it has both delivery and payment issues. */
export function groupInvoiceAlerts(alerts: AttentionItem[]) {
    const groups = new Map<string, AttentionItem[]>()
    for (const alert of alerts) {
        const key = alert.invoice_id || alert.id
        groups.set(key, [...(groups.get(key) ?? []), alert])
    }
    return [...groups.values()]
}
