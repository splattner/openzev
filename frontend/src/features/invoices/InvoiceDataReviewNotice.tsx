import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import type { Invoice, InvoiceReadingImpact } from '../../types/api'

function impactSummary(impact: InvoiceReadingImpact): { key: string; params: Record<string, unknown> } {
    const evidence = impact.evidence
    if (evidence.source === 'csv-reanchor') {
        return {
            key: 'pages.invoices.dataReview.evidenceReanchor',
            params: { count: evidence.changed_readings ?? 0 },
        }
    }
    if (evidence.source === 'import-deletion') {
        const readings = typeof evidence.deleted_readings === 'number' ? evidence.deleted_readings : 0
        return {
            key: 'pages.invoices.dataReview.evidenceDeletion',
            params: {
                count: readings,
            },
        }
    }
    const changes = typeof evidence.change_count === 'number' ? evidence.change_count : 0
    return {
        key: evidence.source === 'csv-import'
            ? 'pages.invoices.dataReview.evidenceCsv'
            : 'pages.invoices.dataReview.evidenceImport',
        params: {
            count: changes,
            delivery: evidence.delivery_id || '?',
            filename: evidence.filename || '?',
        },
    }
}

function reviewMessageKey(status: Invoice['status'], canAct: boolean): string {
    if (status === 'draft') return canAct ? 'draftAction' : 'draftNotice'
    if (status === 'approved' || status === 'sent') return canAct ? 'issuedAction' : 'issuedNotice'
    if (status === 'paid') return 'paidNotice'
    return 'genericNotice'
}

/** Explain reading corrections without changing invoice workflow permissions. */
export function InvoiceDataReviewNotice({
    invoice,
    variant,
    canAct,
}: {
    invoice: Pick<Invoice, 'status' | 'needs_data_review' | 'open_data_impact_count' | 'data_impacts'>
    variant: 'row' | 'detail'
    canAct: boolean
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const [showAll, setShowAll] = useState(false)
    if (!invoice.needs_data_review) return null

    const count = invoice.open_data_impact_count ?? invoice.data_impacts?.length ?? 0
    const impacts = invoice.data_impacts ?? []
    const visibleImpacts = showAll ? impacts : impacts.slice(0, 20)
    const messageKey = `pages.invoices.dataReview.${reviewMessageKey(invoice.status, canAct)}`

    return (
        <div className="warning-banner" style={{ margin: 0, overflowWrap: 'anywhere' }}>
            <div className="actions-row actions-row-wrap">
                <span>{t(messageKey, { count })}</span>
            </div>
            {variant === 'detail' && (invoice.data_impacts ?? []).length > 0 && (
                <ul style={{ margin: '0.5rem 0 0', paddingLeft: '1.1rem' }}>
                    {visibleImpacts.map((impact) => {
                        const summary = impactSummary(impact)
                        return (
                            <li key={impact.id}>
                                {t(summary.key, {
                                    ...summary.params,
                                    from: formatShortDate(impact.evidence.day_from, settings),
                                    to: formatShortDate(impact.evidence.day_to, settings),
                                })}
                                {' · '}
                                {t('pages.invoices.dataReview.flaggedAt', { date: formatShortDate(impact.created_at, settings) })}
                            </li>
                        )
                    })}
                </ul>
            )}
            {variant === 'detail' && impacts.length > 20 && (
                <button type="button" className="button button-secondary button-compact" onClick={() => setShowAll(!showAll)}>
                    {t(showAll ? 'pages.invoices.dataReview.showLess' : 'pages.invoices.dataReview.showAll', { count: impacts.length })}
                </button>
            )}
        </div>
    )
}
