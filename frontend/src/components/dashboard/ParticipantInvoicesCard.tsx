import { useTranslation } from 'react-i18next'
import { InvoiceDocumentsTable } from '../../features/inbox/InvoiceDocuments'
import type { DeliveredDocument } from '../../types/api'
import { Notice } from '../Notice'
import { PageSkeleton } from '../PageSkeleton'

interface ParticipantInvoicesCardProps {
    /** The invoice rows of the participant's inbox; undefined until a response arrives. */
    invoices: DeliveredDocument[] | undefined
    isError: boolean
    isRetrying: boolean
    onRetry: () => void
    showCommunity: boolean
}

export function ParticipantInvoicesCard({ invoices, isError, isRetrying, onRetry, showCommunity }: ParticipantInvoicesCardProps) {
    const { t } = useTranslation()
    const errorNotice = (
        <Notice tone={invoices ? 'warning' : 'error'} onRetry={onRetry} isRetrying={isRetrying}>
            {t('pages.dashboard.failedInvoices')}
        </Notice>
    )
    if (isError && !invoices) return errorNotice

    return (
        <section className="card">
            <h3>{t(showCommunity ? 'pages.dashboard.invoicesAllCommunitiesSection' : 'pages.dashboard.invoicesSection')}</h3>
            {isError && errorNotice}
            {!invoices ? (
                <PageSkeleton variant="tableRows" />
            ) : invoices.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noInvoices')}</p>
            ) : (
                <InvoiceDocumentsTable documents={invoices} showCommunity={showCommunity} />
            )}
        </section>
    )
}
