import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../lib/toast'
import { getLatestEmailLog } from './emailLogs'
import type { InvoicePeriodParticipantRow } from '../../types/api'

const POLL_MS = 2_500
const EMAIL_DELIVERY_TIMEOUT_MS = 90_000

/** An invoice whose queued email is awaited; `announce` toasts its delivery. */
export type EmailTarget = { invoiceId: string; previousLogId: string | null; announce?: boolean }

function settled(rows: Pick<InvoicePeriodParticipantRow, 'invoice'>[], { invoiceId, previousLogId }: EmailTarget) {
    const invoice = rows.find(row => row.invoice?.id === invoiceId)?.invoice
    if (!invoice) return null
    if (['paid', 'cancelled'].includes(invoice.status)) return 'done'
    const latest = getLatestEmailLog(invoice)
    return latest && latest.id !== previousLogId && (latest.status === 'sent' || latest.status === 'failed')
        ? latest.status
        : null
}

/**
 * Refreshes invoice data until every queued email has a new sent/failed
 * attempt, for at most 90 seconds. Tracking ends when `scope` changes.
 */
export function useEmailDelivery({ rows, scope, refreshOverview, refreshRelated, showTimeoutToast = true }: {
    rows: Pick<InvoicePeriodParticipantRow, 'invoice'>[]
    scope: unknown
    refreshOverview: () => void
    refreshRelated: () => void
    showTimeoutToast?: boolean
}) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const [watch, setWatch] = useState<{ until: number; targets: EmailTarget[]; expired?: boolean } | null>(null)

    useEffect(() => {
        setWatch(null)
    }, [scope])

    useEffect(() => {
        if (!watch) return
        const outstanding = watch.targets.filter(target => !settled(rows, target))
        if (outstanding.length < watch.targets.length) {
            if (watch.targets.some(target => target.announce && settled(rows, target) === 'sent')) {
                pushToast(t('pages.invoices.messages.emailSentSuccess'), 'success')
            }
            refreshRelated()
            setWatch(outstanding.length ? { ...watch, targets: outstanding } : null)
            return
        }
        if (watch.expired) return
        const interval = window.setInterval(refreshOverview, POLL_MS)
        const timeout = window.setTimeout(() => {
            setWatch(current => current === watch ? { ...current, expired: true } : current)
            if (showTimeoutToast) pushToast(t('pages.invoices.messages.emailPollingTimeout'), 'error')
        }, Math.max(0, watch.until - Date.now()))
        return () => {
            window.clearInterval(interval)
            window.clearTimeout(timeout)
        }
    }, [watch, rows, refreshOverview, refreshRelated, pushToast, t, showTimeoutToast])

    const track = useCallback((targets: EmailTarget[]) => setWatch(current => ({
        until: Date.now() + EMAIL_DELIVERY_TIMEOUT_MS,
        targets: [
            ...(current && !current.expired ? current.targets : []).filter(old => !targets.some(target => target.invoiceId === old.invoiceId)),
            ...targets,
        ],
    })), [])
    const isTracking = useCallback((invoiceId: string) => !watch?.expired && !!watch?.targets.some(target => target.invoiceId === invoiceId), [watch?.expired, watch?.targets])
    const resumePolling = useCallback(() => setWatch(current => current ? { ...current, expired: false, until: Date.now() + EMAIL_DELIVERY_TIMEOUT_MS } : null), [])

    return useMemo(() => ({
        track,
        isTracking,
        anyTracking: watch !== null && !watch.expired,
        hasTimedOut: watch?.expired ?? false,
        resumePolling,
    }), [track, isTracking, watch, resumePolling])
}
