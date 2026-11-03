import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { useCommunityAccess } from '../../lib/communityAccess'
import { liveCardState, useLiveEnabled, useLiveEnergy } from '../../lib/live'
import { LiveEnergyCard } from './LiveEnergyCard'
import { LivePointsTable } from './LivePointsTable'

/**
 * The "Right now" part of My energy system: the live card and, for managers, viewers and admins, the
 * per-point table. Polling (the snapshot every 15 s) happens only while this is mounted; the first request
 * does not wait for the flag (the server answers 404 while the feature is off). Without live data it says so compactly and points to the setup; the
 * rest of the page (own history) does not depend on it.
 */
export function LiveEnergyView({ zevId }: { zevId: string | undefined }) {
    const { t } = useTranslation()
    const { isZevScope, canManage } = useCommunityAccess()
    const enabledQuery = useLiveEnabled()
    const snapshotQuery = useLiveEnergy(zevId)
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
        // Only who can act gets a button: a manager connects the community's source, a participant their own,
        // and a viewer is told who can (UI patterns §10.3 rule 1).
        const role = canManage ? 'manager' : isZevScope ? 'viewer' : 'participant'
        return (
            <EmptyState
                titleKey="pages.live.empty.title"
                descriptionKey={`pages.live.empty.${role}`}
                actions={role === 'viewer' ? undefined : [{
                    labelKey: `pages.live.empty.${role}Action`,
                    to: role === 'manager' ? '/zev-settings/energy' : '/me/metering-points',
                }]}
            />
        )
    }
    return (
        <>
            <LiveEnergyCard snapshot={snapshot} />
            {snapshot.points && snapshot.points.length > 0 && <LivePointsTable points={snapshot.points} />}
        </>
    )
}
