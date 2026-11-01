import { useTranslation } from 'react-i18next'
import { PageHeader } from '../components/PageHeader'
import { ScopeGuard } from '../components/ScopeGuard'
import { MyEnergyView } from '../features/myEnergy/MyEnergyView'
import { type BillingInterval } from '../lib/billingPeriod'
import { useAuth } from '../lib/auth'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { selectedCommunityName } from '../lib/membership'
import { useBillingPeriodParams } from '../lib/useBillingPeriodParams'

/**
 * My energy system (`/my-energy`, alias `/live`): everything that comes from devices, live and the
 * participant's own history (SPEC-2026-live-energy-data §7). The grid operator's official figures stay on
 * Energy balance. The billing period for the Period view is owned here, as on the dashboard.
 */
export function MyEnergyPage() {
    const { t } = useTranslation()
    const { user } = useAuth()
    const { selectedZevId, selectedZev, entries } = useManagedZev()
    const { isZevScope, isParticipantScope } = useCommunityAccess()
    const scopeNote = useScopeNote()

    const selectedMembership = user?.memberships?.find((membership) => membership.zev === selectedZevId)
    const interval =
        (selectedZev?.billing_interval as BillingInterval | undefined) ?? selectedMembership?.zev_billing_interval
    const { period, setPeriod, isReady: periodReady } = useBillingPeriodParams({
        interval,
        ready: isZevScope ? !!selectedZev : isParticipantScope,
        scopeId: selectedZevId,
        fallback: 'current',
        scopeChange: 'reset',
    })

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedCommunityName({ selectedZev, entries, selectedZevId })}
                communitySwitch
                scopeNote={scopeNote}
                title={t('pages.myEnergy.title')}
                description={t('pages.myEnergy.description')}
            />
            <ScopeGuard skeleton="kpiRow">
                <MyEnergyView interval={interval} period={period} onPeriodChange={setPeriod} periodReady={periodReady} />
            </ScopeGuard>
        </div>
    )
}
