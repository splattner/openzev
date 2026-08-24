import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { fetchInvoice, fetchInvoicePdfBlob, generateInvoicePdf } from '../lib/api/invoices'
import { queryKeys } from '../lib/api/queryKeys'
import { formatShortDate, useAppSettings } from '../lib/appSettings'
import { PdfPreview } from '../components/PdfPreview'

/** Authenticated blob-fetch of the stored PDF artifact → object URL.
 * Fetches from the API endpoint (not /media/) so auth + 401-refresh works
 * everywhere, including Helm/prod where DEBUG=False has no static() serving. */
function useInvoicePdfUrl(invoiceId: string | undefined, hasPdf: boolean): {
    url: string | null
    loading: boolean
    error: boolean
} {
    const [url, setUrl] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)

    useEffect(() => {
        if (!invoiceId || !hasPdf) {
            setUrl(null)
            return
        }
        let objectUrl: string | null = null
        let cancelled = false
        setLoading(true)
        setError(false)
        void fetchInvoicePdfBlob(invoiceId)
            .then((blob) => {
                if (cancelled) return
                if (blob.type !== 'application/pdf') throw new Error('Not a PDF')
                objectUrl = URL.createObjectURL(blob)
                setUrl(objectUrl)
            })
            .catch(() => {
                if (!cancelled) setError(true)
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })
        return () => {
            cancelled = true
            if (objectUrl) URL.revokeObjectURL(objectUrl)
        }
    }, [invoiceId, hasPdf])

    return { url, loading, error }
}

export function InvoiceDetailPage() {
    const { t } = useTranslation()
    const { invoiceId } = useParams<{ invoiceId: string }>()
    const { settings } = useAppSettings()

    const invoiceQuery = useQuery({
        queryKey: queryKeys.invoices.detail(invoiceId as string),
        queryFn: () => fetchInvoice(invoiceId as string),
        enabled: !!invoiceId,
    })

    const [generating, setGenerating] = useState(false)
    const [generateError, setGenerateError] = useState(false)

    // Whether the invoice has a stored PDF artifact (drives the "PDF exists?" branch).
    const pdfExists = invoiceQuery.data?.pdf_url != null

    const { url: pdfObjectUrl, loading: pdfLoading, error: pdfError } = useInvoicePdfUrl(invoiceId, pdfExists)

    if (invoiceQuery.isLoading) {
        return <div className="card">{t('common.loading')}</div>
    }
    if (invoiceQuery.isError || !invoiceQuery.data) {
        return <div className="card error-banner">{t('common.error')}</div>
    }

    const inv = invoiceQuery.data

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
            <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ marginBottom: '0.2rem' }}>{t('pages.invoiceDetail.title', { number: inv.invoice_number })}</h2>
                    <p className="muted" style={{ margin: 0 }}>
                        {inv.participant_name} · {formatShortDate(inv.period_start, settings)} → {formatShortDate(inv.period_end, settings)}
                    </p>
                </div>
                <Link to="/invoices" className="button button-primary" style={{ textDecoration: 'none' }}>
                    {t('pages.invoiceDetail.backToInvoices')}
                </Link>
            </header>

            <section className="grid grid-4">
                <div className="card"><strong>{t('pages.invoiceDetail.status')}</strong><div><span className={`badge badge-${inv.status}`}>{t(`invoice.status.${inv.status}`)}</span></div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.total')}</strong><div>CHF {inv.total_chf}</div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.subtotal')}</strong><div>CHF {inv.subtotal_chf ?? '-'}</div></div>
                <div className="card"><strong>{t('pages.invoiceDetail.vat')}</strong><div>CHF {inv.vat_chf ?? '-'}</div></div>
            </section>

            <section className="card">
                <h3 style={{ marginTop: 0 }}>{t('pages.invoiceDetail.energyTotals')}</h3>
                <div className="inline-form grid grid-4">
                    <div><strong>{t('pages.invoiceDetail.local')}</strong><div>{inv.total_local_kwh ?? '0'} kWh</div></div>
                    <div><strong>{t('pages.invoiceDetail.grid')}</strong><div>{inv.total_grid_kwh ?? '0'} kWh</div></div>
                    <div><strong>{t('pages.invoiceDetail.feedIn')}</strong><div>{inv.total_feed_in_kwh ?? '0'} kWh</div></div>
                </div>
            </section>

            {/* The document itself: the stored PDF artifact, not an HTML facsimile
                that would drift from the issued document. Line-item detail lives
                in the embedded PDF. */}
            <section aria-label={t('pdf.previewTitle')} className="page-stack">
                {pdfExists ? (
                    pdfError ? (
                        <div className="error-banner">{t('common.error')}</div>
                    ) : pdfLoading ? (
                        <div className="card">{t('common.loading')}</div>
                    ) : (
                        <PdfPreview src={pdfObjectUrl} title={t('pages.invoiceDetail.title', { number: inv.invoice_number })} />
                    )
                ) : (
                    <div className="card" style={{ display: 'flex', gap: '1rem', alignItems: 'center', justifyContent: 'space-between' }}>
                        <p className="muted" style={{ margin: 0 }}>
                            {generateError ? <span className="text-error">{t('pdf.generateError')}</span> : t('pdf.noDocument')}
                        </p>
                        <button className="button" type="button" disabled={generating || pdfLoading} onClick={handleGeneratePdf}>
                            {generating ? t('common.loading') : t('pages.invoiceDetail.generatePdf')}
                        </button>
                    </div>
                )}
            </section>
        </div>
    )
}
