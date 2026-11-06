import type { TFunction } from 'i18next'
import type { Notification, NotificationType } from '../types/api'

const KNOWN_TYPES: ReadonlySet<string> = new Set<NotificationType>([
    'invoice.sent',
    'document.delivered',
    'invoice.paid',
    'metering.data',
    'import.finished',
    'import.failed',
    'invoices.generated',
    'invoices.generation_failed',
])

/** Whether this build can render the type; a newer server may send types it cannot. */
export function isKnownNotificationType(type: string): type is NotificationType {
    return KNOWN_TYPES.has(type)
}

/** The line shown for a notification, in the viewer's language (`notifications.types.*`). */
export function notificationText(t: TFunction, notification: Notification): string {
    if (!isKnownNotificationType(notification.type)) return t('notifications.types.unknown')
    return t(`notifications.types.${notification.type}`, { ...notification.payload })
}

/** Where a notification leads, or null when it has no target this build knows. */
export function notificationLink(notification: Notification): string | null {
    if (!isKnownNotificationType(notification.type)) return null
    switch (notification.target_type) {
        case 'invoice':
            if (notification.audience !== 'participant') return `/billing/invoices/${notification.target_id}`
            // A participant reads the invoice in their documents (it was My invoices until #862).
            return '/me/documents'
        case 'document':
            return '/me/documents'
        case 'metering_point':
            return '/me/metering-points'
        case 'import_log':
            return '/metering/imports'
        case 'period':
            return '/billing/invoices'
        default:
            return null
    }
}
