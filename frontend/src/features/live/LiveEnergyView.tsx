import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { useCommunityAccess } from '../../lib/communityAccess'
import { liveCardState, useLiveCurve, useLiveEnabled, useLiveEnergy } from '../../lib/live'
import { LiveCurveChart } from './LiveCurveChart'
import { LiveEnergyCard } from './LiveEnergyCard'
import { LivePointsTable } from './LivePointsTable'

/**
 * The body of the live page: "now" for one ZEV. Polling (the snapshot every 15 s, the curve every
 * minute) happens only while this is mounted, and only once the instance has the feature on.
 */
export function LiveEnergyView({ zevId }: { zevId: string | undefined }) {
    const { t } = useTranslation()
    const { isZevScope } = useCommunityAccess()
    const enabledQuery = useLiveEnabled()
    const enabled = enabledQuery.data === true
    const snapshotQuery = useLiveEnergy(enabled ? zevId : undefined)
    const snapshot = snapshotQuery.data
    const state = liveCardState(snapshot)
    const curve = useLiveCurve(zevId, !!state).data

    if (enabledQuery.isError || snapshotQuery.isError) {
        const failed = enabledQuery.isError ? enabledQuery : snapshotQuery
        return (
            <Notice tone="error" onRetry={() => void failed.refetch()} isRetrying={failed.isFetching}>
                {t('pages.live.loadFailed')}
            </Notice>
        )
    }
    if (enabledQuery.data === false) return <Notice tone="warning">{t('pages.live.disabled')}</Notice>
    if (enabledQuery.isPending || !zevId || snapshot === undefined) return <PageSkeleton variant="kpiRow" />
    if (snapshot === null) return <Notice tone="warning">{t('pages.live.unavailable')}</Notice>
    if (!state) {
        return (
            <EmptyState
                titleKey="pages.live.empty.title"
                descriptionKey={isZevScope ? 'pages.live.empty.manager' : 'pages.live.empty.participant'}
                actions={[{
                    labelKey: isZevScope ? 'pages.live.empty.managerAction' : 'pages.live.empty.participantAction',
                    to: isZevScope ? '/metering/points' : '/me/metering-points',
                }]}
            />
        )
    }
    return (
        <>
            <LiveEnergyCard snapshot={snapshot} />
            {curve && <LiveCurveChart curve={curve} />}
            {snapshot.points && snapshot.points.length > 0 && <LivePointsTable points={snapshot.points} />}
        </>
    )
}
