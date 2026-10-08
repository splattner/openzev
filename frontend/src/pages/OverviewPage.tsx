import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { SetupGuidance } from '../features/overview/SetupGuidance'
import { ScopeGuard } from '../components/ScopeGuard'
import { fetchAttention, fetchReadiness } from '../lib/api/readiness'
import { queryKeys } from '../lib/api/queryKeys'
import { useManagedZev } from '../lib/managedZev'
import { BillingPeriodsPage } from './BillingPeriodsPage'
import { PageHeader } from '../components/PageHeader'
import { useScopeNote } from '../lib/communityAccess'

/** Manager start page: everything that asks for operational attention. */
export function OverviewPage() {
    const { t } = useTranslation()
    const scopeNote = useScopeNote()
    const { selectedZevId, selectedZev } = useManagedZev()

    const readinessQuery = useQuery({
        queryKey: queryKeys.invoices.readiness(selectedZevId || undefined),
        queryFn: () => fetchReadiness(selectedZevId!),
        enabled: !!selectedZevId,
    })
    const attentionQuery = useQuery({
        queryKey: queryKeys.invoices.attention(selectedZevId || undefined),
        queryFn: () => fetchAttention(selectedZevId!),
        enabled: !!selectedZevId,
    })

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedZev?.name}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.overview.title')}
                description={t('pages.overview.description')}
            />

            <ScopeGuard skeleton="card">
                <SetupGuidance readinessQuery={readinessQuery} />
                <BillingPeriodsPage attentionQuery={attentionQuery} />
            </ScopeGuard>
        </div>
    )
}
