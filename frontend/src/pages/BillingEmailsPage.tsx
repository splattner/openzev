import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faEnvelope, faRotate } from '@fortawesome/free-solid-svg-icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useCommunityAccess } from '../lib/communityAccess'
import { EmailLogsModal } from '../components/EmailLogsModal'
import { ScopeGuard } from '../components/ScopeGuard'
import { Notice } from '../components/Notice'
import { PageState } from '../components/PageState'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { fetchEmailLogs, fetchInvoices, retryFailedEmail } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { useManagedZev } from '../lib/managedZev'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import type { EmailLog, Invoice } from '../types/api'

/** Cross-period email delivery state and its canonical delivery history. */

type EmailFilter = 'all' | 'failed' | 'pending' | 'sent'
type RetryRequest = { invoice: Invoice; emailLogId: string }

const FILTERABLE: EmailFilter[] = ['all', 'failed', 'pending', 'sent']

function hasEmailStatus(invoice: Invoice): boolean {
    return invoice.status === 'approved' || invoice.status === 'sent' || invoice.status === 'paid'
}

function badgeFor(status: string | null | undefined): string {
    if (status === 'failed') return 'badge badge-danger'
    if (status === 'sent') return 'badge badge-success'
    if (status === 'pending') return 'badge badge-info'
    return 'badge badge-neutral'
}

export function BillingEmailsPage() {
    const { user } = useAuth()
    const { selectedZevId } = useManagedZev()
    return <BillingEmailsContent key={`${user?.id}:${selectedZevId}`} />
}

function BillingEmailsContent() {
    // Retrying a delivery is a write: a viewer sees the history only (#761).
    const { canManage } = useCommunityAccess()
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { selectedZevId } = useManagedZev()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const [filter, setFilter] = useState<EmailFilter>('all')
    const [queuedLogIds, setQueuedLogIds] = useState<Set<string>>(() => new Set())
    const [historyInvoice, setHistoryInvoice] = useState<Invoice | null>(null)
    const [historyLogs, setHistoryLogs] = useState<EmailLog[]>([])
    const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null)
    const historyRequest = useRef(0)
    const mounted = useRef(false)
    useEffect(() => {
        mounted.current = true
        return () => {
            mounted.current = false
            historyRequest.current += 1
        }
    }, [])

    const statusFilter = 'approved,sent,paid'
    const invoicesQuery = useQuery({
        queryKey: queryKeys.invoices.list(selectedZevId || undefined, statusFilter),
        queryFn: () => fetchInvoices(selectedZevId || undefined, { status: statusFilter }),
        enabled: !!selectedZevId,
        refetchInterval: (query) =>
            query.state.data?.some((invoice) => invoice.last_email_status === 'pending' ||
                (!!invoice.last_email_log_id && queuedLogIds.has(invoice.last_email_log_id)))
                ? 3000
                : false,
    })

    // The worker creates the next log only when it starts. Keep an accepted
    // retry pending locally while polling still returns the old failed log.
    const deliveryInvoices = useMemo(
        () =>
            (invoicesQuery.data ?? [])
                .filter(hasEmailStatus)
                .map((invoice) => invoice.last_email_log_id && queuedLogIds.has(invoice.last_email_log_id)
                    ? { ...invoice, last_email_status: 'pending' as const }
                    : invoice),
        [invoicesQuery.data, queuedLogIds],
    )
    const invoices = deliveryInvoices.filter(
        (invoice) => filter === 'all' || invoice.last_email_status === filter,
    )
    const failedCount = deliveryInvoices.filter((invoice) => invoice.last_email_status === 'failed').length

    const retryMutation = useMutation({
        mutationFn: ({ invoice, emailLogId }: RetryRequest) => {
            if (!mounted.current || !canManage) throw new Error(t('common.error'))
            return retryFailedEmail(invoice.id, emailLogId)
        },
        onSuccess: (_data, { invoice, emailLogId }) => {
            if (!mounted.current) return
            setQueuedLogIds((previous) => new Set([...previous, emailLogId]))
            setHistoryLogs((previous) => previous.map((log) =>
                log.id === emailLogId ? { ...log, status: 'pending' } : log,
            ))
            pushToast(t('pages.billingEmails.retryQueued'), 'success')
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.lists() })
            void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.detail(invoice.id) })
        },
        onError: () => {
            if (mounted.current) pushToast(t('pages.billingEmails.retryFailed'), 'error')
        },
    })

    async function openHistory(invoice: Invoice) {
        const request = ++historyRequest.current
        setHistoryLoadingId(invoice.id)
        try {
            const logs = await fetchEmailLogs(invoice.id)
            if (request !== historyRequest.current) return
            setHistoryInvoice(invoice)
            setHistoryLogs(logs)
        } catch {
            if (request === historyRequest.current) pushToast(t('pages.billingEmails.historyFailed'), 'error')
        } finally {
            if (request === historyRequest.current) setHistoryLoadingId(null)
        }
    }

    const content = (
        <div className="page-stack">
            {failedCount > 0 && (
                <Notice tone="error" role="status">{t('pages.billingEmails.failedBanner', { count: failedCount })}</Notice>
            )}

            <div className="actions-row">
                <label className="inline-form">
                    <span>{t('pages.billingEmails.filter')}</span>
                    <select value={filter} onChange={(event) => setFilter(event.target.value as EmailFilter)}>
                        {FILTERABLE.map((value) => (
                            <option key={value} value={value}>
                                {t(`pages.billingEmails.filters.${value}`)}
                            </option>
                        ))}
                    </select>
                </label>
            </div>

            <section className="table-card">
                <div className="table-scroll">
                    <table className="billing-workflow-table">
                        <thead>
                            <tr>
                                <th>{t('pages.billingEmails.col.invoice')}</th>
                                <th>{t('pages.billingEmails.col.period')}</th>
                                <th>{t('pages.billingEmails.col.participant')}</th>
                                <th>{t('pages.billingEmails.col.emailStatus')}</th>
                                <th>{t('pages.billingEmails.col.actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {invoices.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="muted">{t('pages.billingEmails.empty')}</td>
                                </tr>
                            ) : invoices.map((invoice) => (
                                <tr key={invoice.id}>
                                    <td>{invoice.invoice_number}</td>
                                    <td className="billing-period-cell">
                                        {formatShortDate(invoice.period_start, settings)} →{' '}
                                        {formatShortDate(invoice.period_end, settings)}
                                    </td>
                                    <td>{invoice.participant_name}</td>
                                    <td>
                                        <span className={badgeFor(invoice.last_email_status)}>
                                            {invoice.last_email_status
                                                ? t(`pages.invoices.emailLogs.status.${invoice.last_email_status}`)
                                                : t('pages.billingEmails.noEmailYet')}
                                        </span>
                                    </td>
                                    <td>
                                        <div className="actions-row actions-row-wrap">
                                            <button
                                                type="button"
                                                className="button button-secondary button-compact"
                                                disabled={historyLoadingId === invoice.id}
                                                onClick={() => void openHistory(invoice)}
                                            >
                                                <FontAwesomeIcon icon={faEnvelope} fixedWidth />
                                                {historyLoadingId === invoice.id
                                                    ? t('common.loading')
                                                    : t('pages.billingEmails.viewHistory')}
                                            </button>
                                            {canManage && invoice.last_email_status === 'failed' && invoice.last_email_log_id && (
                                                <button
                                                    type="button"
                                                    className="button button-primary button-compact"
                                                    disabled={retryMutation.isPending}
                                                    onClick={() => retryMutation.mutate({
                                                        invoice,
                                                        emailLogId: invoice.last_email_log_id!,
                                                    })}
                                                >
                                                    <FontAwesomeIcon icon={faRotate} fixedWidth />
                                                    {t('pages.billingEmails.retry')}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </section>

            <EmailLogsModal
                invoiceNumber={historyInvoice?.invoice_number ?? ''}
                emailLogs={historyLogs}
                isOpen={historyInvoice !== null}
                onClose={() => {
                    historyRequest.current += 1
                    setHistoryInvoice(null)
                    setHistoryLogs([])
                    setHistoryLoadingId(null)
                }}
                onRetry={canManage ? (emailLogId) => {
                    if (historyInvoice) retryMutation.mutate({ invoice: historyInvoice, emailLogId })
                } : undefined}
                isRetrying={retryMutation.isPending}
            />
        </div>
    )

    return (
        <ScopeGuard skeleton="tableRows">
            <PageState
                isLoading={invoicesQuery.isLoading}
                isError={invoicesQuery.isError}
                skeleton="tableRows"
                error={t('pages.billingEmails.failed')}
                onRetry={() => void invoicesQuery.refetch()}
                isRetrying={invoicesQuery.isFetching}
            >
                {content}
            </PageState>
        </ScopeGuard>
    )
}
