import { describe, expect, it } from 'vitest'
import { isKnownNotificationType, notificationLink, notificationText } from '../src/lib/notifications'
import type { Notification } from '../src/types/api'

function make(overrides: Partial<Notification> = {}): Notification {
    return {
        id: 'n1',
        type: 'invoice.paid',
        audience: 'participant',
        zev: 'z1',
        zev_name: 'ZEV One',
        payload: { invoice_number: 'INV-1' },
        target_type: 'invoice',
        target_id: 'inv-1',
        created_at: '2026-03-01T10:00:00Z',
        read_at: null,
        ...overrides,
    }
}

describe('notificationLink', () => {
    it('sends a participant to their invoice list and a manager to the invoice', () => {
        expect(notificationLink(make())).toBe('/me/invoices')
        expect(notificationLink(make({ audience: 'manager' }))).toBe('/billing/invoices/inv-1')
    })

    it('maps the other targets', () => {
        expect(notificationLink(make({ type: 'metering.data', target_type: 'metering_point' }))).toBe('/me/metering-points')
        expect(notificationLink(make({ type: 'import.failed', audience: 'manager', target_type: 'import_log' }))).toBe('/metering/imports')
        expect(notificationLink(make({ type: 'invoices.generated', audience: 'manager', target_type: 'period' }))).toBe('/billing/invoices')
    })

    it('has no link for a type or target this build does not know', () => {
        expect(notificationLink(make({ type: 'future.event' }))).toBeNull()
        expect(notificationLink(make({ target_type: '' }))).toBeNull()
    })
})

describe('notificationText', () => {
    it('renders a known type through its translation key with the payload', () => {
        const calls: Array<[string, unknown]> = []
        const t = ((key: string, options?: unknown) => { calls.push([key, options]); return key }) as never
        expect(notificationText(t, make())).toBe('notifications.types.invoice.paid')
        expect(calls[0]).toEqual(['notifications.types.invoice.paid', { invoice_number: 'INV-1' }])
    })

    it('falls back for an unknown type', () => {
        const t = ((key: string) => key) as never
        expect(notificationText(t, make({ type: 'future.event' }))).toBe('notifications.types.unknown')
        expect(isKnownNotificationType('future.event')).toBe(false)
    })
})
