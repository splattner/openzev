import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { IssueText } from '../../components/IssueText'
import { formatShortDate, useAppSettings } from '../../lib/appSettings'
import { useAuth } from '../../lib/auth'
import { relationToZev, useCommunityAccess } from '../../lib/communityAccess'
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
    canAct = false,
    action,
}: {
    invoice: Pick<Invoice, 'zev' | 'status' | 'needs_data_review' | 'open_data_impact_count' | 'data_impacts'>
    canAct?: boolean
    action?: ReactNode
}) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { user } = useAuth()
    const { isZevScope } = useCommunityAccess()
    const [showAll, setShowAll] = useState(false)
    if (!invoice.needs_data_review) return null

    const relation = relationToZev(user, invoice.zev)
    const canOpenImports = isZevScope && (relation === 'admin' || relation === 'manager' || relation === 'viewer')

    const count = invoice.open_data_impact_count ?? invoice.data_impacts?.length ?? 0
    const impacts = invoice.data_impacts ?? []
    const visibleImpacts = showAll ? impacts : impacts.slice(0, 20)
    const messageKey = `pages.invoices.dataReview.${reviewMessageKey(invoice.status, canAct)}`

    return (
        <div className="invoice-data-review">
            <p className="m-0"><IssueText>{t(messageKey, { count })}</IssueText></p>
            {action && <div className="mt-05">{action}</div>}
            {impacts.length > 0 && (
                <div className="invoice-data-review-evidence page-stack mt-05">
                    {visibleImpacts.map((impact) => {
                        const summary = impactSummary(impact)
                        return (
                            <p className="m-0" key={impact.id}>
                                {t(summary.key, {
                                    ...summary.params,
                                    from: formatShortDate(impact.evidence.day_from, settings),
                                    to: formatShortDate(impact.evidence.day_to, settings),
                                })}
                                {' · '}
                                {t('pages.invoices.dataReview.flaggedAt', { date: formatShortDate(impact.created_at, settings) })}
                                {canOpenImports && impact.import_log && (
                                    <>
                                        {' · '}
                                        <Link
                                            className="table-inline-link"
                                            to={`/metering/imports?${new URLSearchParams({
                                                import: impact.import_log,
                                                ...(impact.evidence.day_from && impact.evidence.day_to ? {
                                                    change_from: impact.evidence.day_from,
                                                    change_to: impact.evidence.day_to,
                                                } : {}),
                                            })}#correction-history`}
                                        >
                                            {t('pages.invoices.dataReview.openImport')}
                                            <span aria-hidden="true">→</span>
                                        </Link>
                                    </>
                                )}
                            </p>
                        )
                    })}
                </div>
            )}
            {impacts.length > 20 && (
                <button type="button" className="button button-secondary button-compact" onClick={() => setShowAll(!showAll)}>
                    {t(showAll ? 'pages.invoices.dataReview.showLess' : 'pages.invoices.dataReview.showAll', { count: impacts.length })}
                </button>
            )}
        </div>
    )
}
