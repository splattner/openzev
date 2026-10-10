import { useTranslation } from 'react-i18next'
import { useAuth } from '../lib/auth'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { selectedCommunityName } from '../lib/membership'
import { useManagedZev } from '../lib/managedZev'
import { ScopeGuard } from '../components/ScopeGuard'
import { PageHeader } from '../components/PageHeader'
import { ManagementDashboardBody } from '../features/dashboard/ManagementDashboardBody'
import { ParticipantDashboardBody } from '../features/dashboard/ParticipantDashboardBody'
import { type BillingInterval } from '../lib/billingPeriod'
import { useBillingPeriodParams } from '../lib/useBillingPeriodParams'

export function DashboardPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const scopeNote = useScopeNote()
    const { entries, selectedZevId, selectedZev } = useManagedZev()
    const { isZevScope: isZevScopedRole, isParticipantScope } = useCommunityAccess()

    const selectedMembership = user?.memberships?.find((membership) => membership.zev === selectedZevId)
    const interval =
        (selectedZev?.billing_interval as BillingInterval | undefined) ?? selectedMembership?.zev_billing_interval
    const { period, setPeriod, isReady: periodReady } = useBillingPeriodParams({
        interval,
        ready: isZevScopedRole ? !!selectedZev : isParticipantScope,
        scopeId: selectedZevId,
        fallback: 'current',
        scopeChange: 'reset',
    })
    const periodProps = { interval, period, onPeriodChange: setPeriod, periodReady }

    const scopeName = selectedCommunityName({ selectedZev, entries, selectedZevId })
    let descriptionKey = 'dashboard.description'
    if (isZevScopedRole) descriptionKey = 'pages.energyBalancePage.description'
    else if (isParticipantScope) descriptionKey = 'dashboard.participantDescription'

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={scopeName}
                communitySwitch
                scopeNote={scopeNote}
                title={t(isZevScopedRole ? 'pages.energyBalancePage.title' : 'dashboard.title')}
                description={t(descriptionKey)}
            />

            <ScopeGuard skeleton="kpiRow">
                {isZevScopedRole ? (
                    <ManagementDashboardBody {...periodProps} />
                ) : isParticipantScope ? (
                    <ParticipantDashboardBody {...periodProps} />
                ) : null}
            </ScopeGuard>
        </div>
    )
}
