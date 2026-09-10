import type { TFunction } from 'i18next'
import type { AttentionItem, ReadinessStep } from '../../types/api'

/** Maps a next_action back to the step that owns it (for its open link). */
export const NEXT_ACTION_STEP_KEY: Record<string, string> = {
    fix_metering: 'metering',
    fix_assignments: 'assignments',
    fix_tariffs: 'tariffs',
    generate: 'generated',
    review_generation_conflicts: 'generation_conflicts',
    approve: 'approved',
    send: 'sent',
    track_payments: 'paid',
}
export function stepDetailText(step: ReadinessStep, t: TFunction): string | null {
    const d = (key: string, vars: Record<string, unknown> = {}) =>
        t(`pages.dashboard.cockpit.stepDetails.${key}`, vars)
    switch (step.key) {
        case 'metering':
            if (step.status !== 'warn') return null
            return d('meteringWarn', {
                count: step.count,
                days: step.detail_data?.missing_days ?? 0,
            })
        case 'assignments':
            if (step.status !== 'warn') return null
            return d('assignmentsWarn', { readings: step.count })
        case 'tariffs':
            if (step.status === 'todo') return d('tariffsTodo')
            if (step.status === 'warn') {
                return d('tariffsWarn', { days: step.count, total: step.total ?? 0 })
            }
            return null
        case 'generated':
            if (step.status !== 'todo') return null
            return d('generatedTodo', {
                missing: step.detail_data?.missing ?? Math.max(0, (step.total ?? 0) - step.count),
                total: step.total ?? 0,
            })
        case 'generation_conflicts': {
            if (step.status !== 'warn') return null
            const names = (step.detail_data?.conflicts ?? [])
                .slice(0, 3)
                .map((conflict) => conflict.participant_name)
                .join(', ')
            return d('conflictsWarn', {
                count: step.detail_data?.conflict_count ?? step.count,
                names,
            })
        }
        case 'approved':
            if (step.status !== 'todo') return null
            return d('approvedTodo', { count: step.count })
        case 'sent': {
            if (step.status !== 'todo') return null
            const parts: string[] = []
            if (step.count > 0) parts.push(d('sentTodo', { count: step.count }))
            if (step.failed) parts.push(d('emailFailedTodo', { failed: step.failed }))
            return parts.length > 0 ? parts.join(' · ') : null
        }
        case 'paid':
            if (step.status !== 'todo') return null
            return d('paidTodo', {
                unpaid: step.detail_data?.unpaid ?? (step.total ?? 0) - step.count,
                total: step.total ?? 0,
            })
        default:
            return null
    }
}

/** Cross-period alerts only: the attention types the cockpit cannot show as
 * steps. Localized from the structured fields — the English `label` fallback
 * is never rendered. */
export function attentionText(item: AttentionItem, t: TFunction, format: (v: string) => string): string {
    switch (item.type) {
        case 'email_failed':
            return t('pages.dashboard.attention.text.emailFailed', {
                number: item.invoice_number,
                recipient: item.recipient,
            })
        case 'invoice_overdue':
            return t('pages.dashboard.attention.text.invoiceOverdue', {
                number: item.invoice_number,
                due: format(item.due_date ?? ''),
            })
        case 'participant_validity':
            return item.expired
                ? t('pages.dashboard.attention.text.participantExpired', {
                      name: item.participant_name,
                      validTo: format(item.valid_to ?? ''),
                  })
                : t('pages.dashboard.attention.text.participantExpiring', {
                      name: item.participant_name,
                      validTo: format(item.valid_to ?? ''),
                  })
        default:
            return item.label
    }
}
