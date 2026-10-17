import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import {
    fetchInvoice,
    fetchInvoicePdfBlob,
    generateInvoicePdf,
    revokeInvoiceAccessLink,
} from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { useAuth } from '../lib/auth'
import { scopeNoteKey, shellRoleForZev } from '../lib/communityAccess'
import { PdfPreview } from '../components/PdfPreview'
import { InvoiceAccessLinkCard } from '../features/invoices/InvoiceAccessLinkCard'
import { InvoiceAppliedCreditsCard } from '../features/invoices/InvoiceAppliedCreditsCard'
import { InvoiceCreditsCard } from '../features/invoices/InvoiceCreditsCard'
import { amountDueChf, canCorrectInvoice, hasCreditApplied } from '../features/invoices/invoiceCredits'
import { InvoicePaymentsCard } from '../features/invoices/InvoicePaymentsCard'
import type { Invoice } from '../types/api'

import { usePdfObjectUrl } from '../lib/usePdfObjectUrl'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { StatCard } from '../components/StatCard'
import { InvoiceStatusBadge } from '../components/InvoicePresentation'
import { formatChf, formatChfAmount, formatKwh } from '../lib/numbers'

export function InvoiceDetailPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const location = useLocation()
    const { invoiceId } = useParams<{ invoiceId: string }>()
    const { settings } = useAppSettings()
    const queryClient = useQueryClient()
    // Participants reach this page for their own invoices; revoking is a
    // management control and must not be offered to the person holding the QR.
    // Decided by the invoice's own community, which need not be the selected
    // one (an account may manage one ZEV and rent in another, #761).

    const invoiceQuery = useQuery({
        queryKey: queryKeys.invoices.detail(invoiceId as string),
        queryFn: () => fetchInvoice(invoiceId as string),
        enabled: !!invoiceId,
    })

    const [generating, setGenerating] = useState(false)
    const [generateError, setGenerateError] = useState(false)

    // Whether the invoice has a stored PDF artifact (drives the "PDF exists?" branch).
    const pdfExists = invoiceQuery.data?.pdf_url != null

    // Keep the fetcher stable across renders to avoid repeated PDF requests.
    const pdfFetcher = useMemo(
        () => (invoiceId ? (signal: AbortSignal) => fetchInvoicePdfBlob(invoiceId, signal) : null),
        [invoiceId],
    )
    const openPdfInNewTab = useMemo(
        () => (invoiceId ? () => fetchInvoicePdfBlob(invoiceId) : undefined),
        [invoiceId],
    )
    const { url: pdfObjectUrl, loading: pdfLoading, error: pdfError } = usePdfObjectUrl(pdfFetcher, pdfExists)

    const pendingHeader = <PageHeader title={t('pages.invoices.title')} />
    if (invoiceQuery.isLoading) {
        return <div className="page-stack">{pendingHeader}<PageSkeleton variant="card" /></div>
    }
    if (invoiceQuery.isError || !invoiceQuery.data) {
        return <div className="page-stack">{pendingHeader}<Notice tone="error" onRetry={() => void invoiceQuery.refetch()} isRetrying={invoiceQuery.isFetching}>{t('common.error')}</Notice></div>
    }

    const inv = invoiceQuery.data

    // Return link follows its origin (the invoice period it came from, or My
    // invoices); participants without
    // one fall back to /me/invoices.
    const invoiceShellRole = shellRoleForZev(user, invoiceQuery.data?.zev)
    // The invoice's own community, which may not be the selected one.
    const invoiceScopeNoteKey = scopeNoteKey(invoiceShellRole)
    const canManageAccessLink = invoiceShellRole === 'admin' || invoiceShellRole === 'manager'
    const isParticipant = invoiceShellRole === 'participant' || invoiceShellRole === 'former'
    const origin = (location.state as { from?: string; period_start?: string; period_end?: string } | null)
    const isoDay = /^\d{4}-\d{2}-\d{2}$/
    const originPeriod =
        origin?.from === '/billing/invoices'
        && origin.period_start && isoDay.test(origin.period_start)
        && origin.period_end && isoDay.test(origin.period_end)
            ? `/billing/invoices?period_start=${origin.period_start}&period_end=${origin.period_end}`
            : null
    const backHref = isParticipant
        ? origin?.from === '/' || origin?.from === '/me/invoices' || origin?.from === '/me/statement'
            ? origin.from
            : '/me/invoices'
        : origin?.from === '/'
            ? '/'
            : user?.role === 'admin' && origin?.from === '/admin/invoices'
                ? '/admin/invoices'
            : originPeriod ?? '/billing/invoices'
    const backLabel = isParticipant
        ? t('common.back')
        : t('pages.invoiceDetail.backToInvoices')

    // A payment changes the status and totals every invoice list shows.
    const handleInvoiceChanged = (updated: Invoice) => {
        queryClient.setQueryData(queryKeys.invoices.detail(updated.id), updated)
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.lists() })
        void queryClient.invalidateQueries({ queryKey: ['invoices', 'period-overview'] })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.mine() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.credits() })
        for (const key of ['readiness', 'readiness-list', 'attention']) {
            void queryClient.invalidateQueries({ queryKey: ['invoices', key] })
        }
    }

    // A refund leaves the invoice's own payload alone but changes what its credit notes show.
    const handleCreditChanged = () => {
        if (invoiceId) void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.detail(invoiceId) })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.credits() })
        void queryClient.invalidateQueries({ queryKey: queryKeys.invoices.mine() })
    }

    const handleGeneratePdf = async () => {
        if (!invoiceId) return
        setGenerating(true)
        setGenerateError(false)
        try {
            await generateInvoicePdf(invoiceId)
            // Re-fetch the invoice so the new `pdf_url` drives the embed.
            await invoiceQuery.refetch()
        } catch {
            setGenerateError(true)
        } finally {
            setGenerating(false)
        }
    }

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={inv.zev_name}
                scopeNote={invoiceScopeNoteKey ? t(invoiceScopeNoteKey) : undefined}
                title={t('pages.invoiceDetail.title', { number: inv.invoice_number })}
                description={
                    // The document's own header: status pill, recipient, period.
                    <span className="invoice-detail-meta">
                        <span className="visually-hidden">{t('pages.invoiceDetail.status')}: </span>
                        <InvoiceStatusBadge status={inv.status} paidChf={inv.paid_chf} />
                        <span>{`${inv.participant_name} · ${formatShortDate(inv.period_start, settings)} → ${formatShortDate(inv.period_end, settings)}`}</span>
                        {inv.replaced_by ? (
                            <span>
                                {t('pages.invoiceDetail.replacedBy')}{' '}
                                <Link to={`/billing/invoices/${inv.replaced_by.id}`} state={location.state}>{inv.replaced_by.invoice_number}</Link>
                            </span>
                        ) : null}
                        {inv.replaces?.length ? (
                            <span>
                                {t('pages.invoiceDetail.replaces')}{' '}
                                {inv.replaces.map((ref, index) => (
                                    <span key={ref.id}>
                                        {index > 0 && ', '}
                                        <Link to={`/billing/invoices/${ref.id}`} state={location.state}>{ref.invoice_number}</Link>
                                    </span>
                                ))}
                            </span>
                        ) : null}
                    </span>
                }
                actions={
                    <Link to={backHref} className="button button-secondary">
                        {backLabel}
                    </Link>
                }
            />

            {/* The figures of the invoice, as its summary tiles print them. */}
            <div className="invoice-figures">
                <section className="stat-grid">
                    <StatCard
                        accent
                        label={t('pages.invoiceDetail.total')}
                        value={formatChfAmount(Number(inv.total_chf))}
                        currency="CHF"
                        hint={hasCreditApplied(inv) ? t('pages.invoiceDetail.amountDueHint', { amount: formatChf(amountDueChf(inv)) }) : undefined}
                    />
                    <StatCard label={t('pages.invoiceDetail.subtotal')} value={inv.subtotal_chf != null ? formatChfAmount(Number(inv.subtotal_chf)) : null} currency="CHF" />
                    <StatCard label={t('pages.invoiceDetail.vat')} value={inv.vat_chf != null ? formatChfAmount(Number(inv.vat_chf)) : null} currency="CHF" />
                </section>
                <section className="stat-grid" aria-label={t('pages.invoiceDetail.energyTotals')}>
                    <StatCard label={t('pages.invoiceDetail.local')} value={formatKwh(Number(inv.total_local_kwh ?? 0))} unit="kWh" />
                    <StatCard label={t('pages.invoiceDetail.grid')} value={formatKwh(Number(inv.total_grid_kwh ?? 0))} unit="kWh" />
                    <StatCard label={t('pages.invoiceDetail.feedIn')} value={formatKwh(Number(inv.total_feed_in_kwh ?? 0))} unit="kWh" />
                </section>
            </div>

            <InvoiceAppliedCreditsCard invoice={inv} />

            {/* `payments` is null for a participant, who sees the totals only. */}
            {!isParticipant && inv.payments != null && (
                <InvoicePaymentsCard invoice={inv} canManage={canManageAccessLink} onChanged={handleInvoiceChanged} />
            )}

            {/* A credit note exists for the participant from the moment it is issued. */}
            {((inv.credits ?? []).length > 0 || canCorrectInvoice(inv, canManageAccessLink)) && (
                <InvoiceCreditsCard
                    invoice={inv}
                    canManage={canManageAccessLink}
                    onChanged={handleInvoiceChanged}
                    onCreditChanged={handleCreditChanged}
                />
            )}

            {canManageAccessLink && inv.access_link != null && (
                <InvoiceAccessLinkCard
                    link={inv.access_link}
                    onRevoke={async () => {
                        if (!invoiceId) return
                        await revokeInvoiceAccessLink(invoiceId)
                        await invoiceQuery.refetch()
                    }}
                />
            )}

            {/* The document itself: the stored PDF artifact, not an HTML facsimile
                that would drift from the issued document. Line-item detail lives
                in the embedded PDF. */}
            <section aria-label={t('pdf.previewTitle')} className="page-stack">
                {generating ? (
                    <div className="page-stack">
                        <p className="muted" role="status" aria-live="polite">
                            {t('pages.invoiceDetail.generatingPdf')}
                        </p>
                        <PageSkeleton variant="card" />
                    </div>
                ) : pdfExists ? (
                    pdfError ? (
                        <div className="error-banner">{t('common.error')}</div>
                    ) : pdfLoading ? (
                        <PageSkeleton variant="card" />
                    ) : (
                        <PdfPreview src={pdfObjectUrl} title={t('pages.invoiceDetail.title', { number: inv.invoice_number })} openInNewTabFetcher={openPdfInNewTab} />
                    )
                ) : (
                    <div className="card pdf-missing">
                        <p className="muted m-0">
                            {generateError ? <span className="text-error">{t('pdf.generateError')}</span> : t('pdf.noDocument')}
                        </p>
                        {/* PDF generation takes a manager of the invoice's ZEV (#761). */}
                        {canManageAccessLink ? (
                            <button className="button" type="button" disabled={generating || pdfLoading} onClick={handleGeneratePdf}>
                                {generating ? t('common.loading') : t('pages.invoiceDetail.generatePdf')}
                            </button>
                        ) : null}
                    </div>
                )}
            </section>
        </div>
    )
}
