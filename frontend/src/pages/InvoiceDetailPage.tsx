import { useQuery } from '@tanstack/react-query'
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

import { usePdfObjectUrl } from '../lib/usePdfObjectUrl'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { StatCard } from '../components/StatCard'
import { InvoiceStatusBadge } from '../components/InvoicePresentation'
import { formatChf, formatKwh } from '../lib/numbers'

export function InvoiceDetailPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const location = useLocation()
    const { invoiceId } = useParams<{ invoiceId: string }>()
    const { settings } = useAppSettings()
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
                        <InvoiceStatusBadge status={inv.status} />
                        <span>{`${inv.participant_name} · ${formatShortDate(inv.period_start, settings)} → ${formatShortDate(inv.period_end, settings)}`}</span>
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
                    <StatCard accent label={t('pages.invoiceDetail.total')} value={formatChf(Number(inv.total_chf))} />
                    <StatCard label={t('pages.invoiceDetail.subtotal')} value={inv.subtotal_chf != null ? formatChf(Number(inv.subtotal_chf)) : '—'} />
                    <StatCard label={t('pages.invoiceDetail.vat')} value={inv.vat_chf != null ? formatChf(Number(inv.vat_chf)) : '—'} />
                </section>
                <section className="stat-grid" aria-label={t('pages.invoiceDetail.energyTotals')}>
                    <StatCard label={t('pages.invoiceDetail.local')} value={`${formatKwh(Number(inv.total_local_kwh ?? 0))} kWh`} />
                    <StatCard label={t('pages.invoiceDetail.grid')} value={`${formatKwh(Number(inv.total_grid_kwh ?? 0))} kWh`} />
                    <StatCard label={t('pages.invoiceDetail.feedIn')} value={`${formatKwh(Number(inv.total_feed_in_kwh ?? 0))} kWh`} />
                </section>
            </div>

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
