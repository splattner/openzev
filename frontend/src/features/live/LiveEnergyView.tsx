import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { useCommunityAccess } from '../../lib/communityAccess'
import { liveCardState, useLiveEnabled, useLiveEnergy } from '../../lib/live'
import { LiveEnergyCard } from './LiveEnergyCard'
import { LivePointsTable } from './LivePointsTable'
import { ProductionForecastSection } from './ProductionForecastChart'

/**
 * The "Right now" part of My energy system: the live card and, for managers, viewers and admins, the
 * per-point table. Polling (the snapshot every 15 s) happens only while this is mounted, and only once
 * the instance has the feature on. Without live data it says so compactly and points to the setup; the
 * rest of the page (own history) does not depend on it.
 */
export function LiveEnergyView({ zevId }: { zevId: string | undefined }) {
    const { t } = useTranslation()
    const { isZevScope } = useCommunityAccess()
    const enabledQuery = useLiveEnabled()
    const enabled = enabledQuery.data === true
    const snapshotQuery = useLiveEnergy(enabled ? zevId : undefined)
    const snapshot = snapshotQuery.data
    const state = liveCardState(snapshot)

    if (enabledQuery.isError || snapshotQuery.isError) {
        const failed = enabledQuery.isError ? enabledQuery : snapshotQuery
        return (
            <Notice tone="error" onRetry={() => void failed.refetch()} isRetrying={failed.isFetching}>
                {t('pages.live.loadFailed')}
            </Notice>
        )
    }
    if (enabledQuery.data === false) return <p className="muted">{t('pages.live.disabled')}</p>
    if (enabledQuery.isPending || !zevId || snapshot === undefined) return <PageSkeleton variant="kpiRow" />
    if (snapshot === null) return <Notice tone="warning">{t('pages.live.unavailable')}</Notice>
    if (!state) {
        return (
            <>
            <EmptyState
                titleKey="pages.live.empty.title"
                descriptionKey={isZevScope ? 'pages.live.empty.manager' : 'pages.live.empty.participant'}
                actions={[{
                    labelKey: isZevScope ? 'pages.live.empty.managerAction' : 'pages.live.empty.participantAction',
                    to: isZevScope ? '/metering/points' : '/me/metering-points',
                }]}
            />
            <ProductionForecastSection zevId={zevId} enabled={enabled} />
            </>
        )
    }
    return (
        <>
            <LiveEnergyCard snapshot={snapshot} />
            {snapshot.points && snapshot.points.length > 0 && <LivePointsTable points={snapshot.points} />}
            <ProductionForecastSection zevId={zevId} enabled={enabled} />
        </>
    )
}
