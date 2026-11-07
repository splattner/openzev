import type { TFunction } from 'i18next'
import { formatShortDate } from '../../lib/appSettings'
import type { AppSettings, AuditEvent } from '../../types/api'

/**
 * The words for an audit event, in the reader's language.
 *
 * The backend stores one English sentence per event (`summary`) so the log
 * stays searchable and readable outside the app. The app does not show it:
 * the event is named from its `action_type`, and the names it applies to come
 * from the structured fields. A type the app has no name for yet falls back to
 * the stored sentence rather than to a code.
 */
export function auditActionLabel(t: TFunction, event: Pick<AuditEvent, 'action_type' | 'summary'>): string {
    return t(`pages.auditLogs.events.${event.action_type}`, { defaultValue: event.summary })
}

/** What the event was about: the target's own name, or the period of a batch run. */
export function auditTargetLabel(
    event: Pick<AuditEvent, 'target_display' | 'metadata_json'>,
    settings: AppSettings,
): string {
    if (event.target_display) return event.target_display
    const metadata = event.metadata_json ?? {}
    const from = typeof metadata.period_start === 'string' ? metadata.period_start : ''
    const to = typeof metadata.period_end === 'string' ? metadata.period_end : ''
    if (from && to) return `${formatShortDate(from, settings)} – ${formatShortDate(to, settings)}`
    return ''
}

const AUTOMATIC_SOURCES = new Set(['system', 'celery', 'management_command'])

/** Who did it: a person's name, or the kind of process or link that acted without one. */
export function auditActorLabel(t: TFunction, event: Pick<AuditEvent, 'actor_display' | 'source'>): string {
    if (event.actor_display) return event.actor_display
    if (AUTOMATIC_SOURCES.has(event.source)) return t('pages.auditLogs.actorSystem')
    if (event.source === 'invoice_link' || event.source === 'onboarding_link') {
        return t(`pages.auditLogs.sources.${event.source}`)
    }
    return t('pages.auditLogs.actorAnonymous')
}
