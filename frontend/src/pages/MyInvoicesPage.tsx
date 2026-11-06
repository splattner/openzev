import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { listInboxDocuments } from '../lib/api/inbox'
import { queryKeys } from '../lib/api/queryKeys'
import { PageSkeleton } from '../components/PageSkeleton'
import { useAuth } from '../lib/auth'
import { ownParticipantIds, soleCommunityName } from '../lib/membership'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'
import { CreditNoteDocumentsTable, InvoiceDocumentsTable } from '../features/inbox/InvoiceDocuments'

/**
 * Participant's own invoices and credit notes (`/me/invoices`): the invoice and credit note rows of
 * the document inbox (SPEC-2026-11-participant-document-inbox §7.1), with the figures each row
 * carries. The same list, unfiltered, is *My documents*. A former participant still reads what it
 * was sent.
 */
export function MyInvoicesPage() {
    const { t } = useTranslation()
    const { user } = useAuth()

    const query = useQuery({ queryKey: queryKeys.inbox.list('mine'), queryFn: () => listInboxDocuments() })
    const own = useMemo(() => ownParticipantIds(user), [user])
    const mine = useMemo(
        () => (query.data ?? []).filter((document) => document.participant != null && own.has(document.participant)),
        [query.data, own],
    )
    const invoices = mine.filter((document) => document.kind === 'invoice')
    const credits = mine.filter((document) => document.kind === 'credit_note')
    // Several memberships: a community column, and the header names all of them.
    const showCommunity = (user?.memberships?.length ?? 0) > 1

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={showCommunity ? t('pages.myInvoices.allCommunities') : soleCommunityName(user)}
                title={t('pages.myInvoices.title')}
                description={t('pages.myInvoices.description')}
            />

            {query.isError && query.data && (
                <Notice tone="warning" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>{t('pages.myInvoices.failed')}</Notice>
            )}
            {query.isLoading ? (
                <PageSkeleton variant="tableRows" />
            ) : query.isError && !query.data ? (
                <Notice tone="error" onRetry={() => void query.refetch()} isRetrying={query.isFetching}>{t('pages.myInvoices.failed')}</Notice>
            ) : invoices.length === 0 ? (
                <div className="card">
                    <h3 className="mt-0">{t('pages.myInvoices.empty.title')}</h3>
                    <p className="muted">{t('pages.myInvoices.empty.description')}</p>
                </div>
            ) : (
                <section className="table-card">
                    <InvoiceDocumentsTable documents={invoices} showCommunity={showCommunity} />
                </section>
            )}

            {credits.length > 0 && (
                <section className="table-card" aria-labelledby="my-credits-title">
                    <h3 id="my-credits-title">{t('pages.myInvoices.credits.title')}</h3>
                    <p className="muted">{t('pages.myInvoices.credits.description')}</p>
                    <CreditNoteDocumentsTable documents={credits} />
                </section>
            )}
        </div>
    )
}
