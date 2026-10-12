import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { BehindMeterBadge } from '../components/BehindMeterBadge'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { ScopeGuard } from '../components/ScopeGuard'
import { MeteringDataLink } from '../features/supplementary/MeteringDataLink'
import { MeteringPointEnergyData } from '../features/supplementary/MeteringPointEnergyData'
import { queryKeys } from '../lib/api/queryKeys'
import { listSupplementarySources } from '../lib/api/supplementary'
import { fetchMeteringPoints } from '../lib/api/zev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { selectedCommunityName } from '../lib/membership'
import { useEnergyDataEligibility } from '../lib/supplementary'
import type { MeteringPoint } from '../types/api'

/**
 * The participant's own metering points (`/me/metering-points`). Where one has generation behind
 * the meter and the participant holds it personally, the energy data of that meter is set up
 * here: connect a source, see its status, sync, disconnect. The credential belongs to the
 * participant's account and is never shown to a manager (SPEC-2026-supplementary-energy-data §7.1).
 *
 * A manager who is also a participant reaches the page from their own energy data call to action;
 * they see the meters they hold with generation behind them, not the community's.
 */
export function MyMeteringPointsPage() {
    const { t } = useTranslation()
    const { selectedZevId, selectedZev, entries } = useManagedZev()
    const scopeNote = useScopeNote()

    return (
        <div className="page-stack">
            <PageHeader
                eyebrow={selectedCommunityName({ selectedZev, entries, selectedZevId })}
                scopeNote={scopeNote}
                title={t('pages.myMeteringPoints.title')}
                description={t('pages.myMeteringPoints.description')}
            />
            <ScopeGuard>
                <MyMeteringPointsView />
            </ScopeGuard>
        </div>
    )
}

function MyMeteringPointsView() {
    const { t } = useTranslation()
    const { selectedZevId } = useManagedZev()
    const { isParticipantScope } = useCommunityAccess()
    const energyData = useEnergyDataEligibility()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    // A participant is only offered their own meters by the list; a manager's list is the whole
    // community's, so for them the page shows just the meters they hold with generation behind them.
    const pointsQuery = useQuery({
        queryKey: queryKeys.metering.points(selectedZevId || undefined),
        queryFn: () => fetchMeteringPoints(selectedZevId || undefined),
        enabled: isParticipantScope && !!selectedZevId,
    })
    const sourcesQuery = useQuery({
        queryKey: queryKeys.metering.supplementarySources(),
        queryFn: listSupplementarySources,
        enabled: energyData.featureOn,
    })

    const eligible = energyData.eligible.filter((point) => point.zev === selectedZevId)
    const eligibleByPoint = new Map(eligible.map((point) => [point.metering_point, point]))
    // The key is shared with the metering points page, so a disabled query can still hold the
    // community's whole list from a visit there: only a participant's own list is used.
    const ownPoints = isParticipantScope ? (pointsQuery.data ?? []) : []
    const plainPoints = ownPoints.filter((point) => !eligibleByPoint.has(point.id))
    const sources = sourcesQuery.data ?? []

    const loading = energyData.isLoading || (isParticipantScope && pointsQuery.isLoading)
    if (loading) return <PageSkeleton variant="cardList" />
    // The list query shares its key with the metering points page, so only a participant's own
    // request may fail this page: a manager's disabled one can still carry that page's error.
    if (isParticipantScope && pointsQuery.isError && !pointsQuery.data) {
        return <Notice tone="error" onRetry={() => void pointsQuery.refetch()} isRetrying={pointsQuery.isFetching}>{t('pages.myMeteringPoints.loadFailed')}</Notice>
    }

    // A failed eligibility check says nothing about the feature: it must not read as "off" or "nothing to connect".
    if (energyData.isError) {
        return (
            <Notice tone="error" onRetry={() => void energyData.refetch()} isRetrying={energyData.isFetching}>
                {t('supplementary.section.eligibilityError')}
            </Notice>
        )
    }

    const isEmpty = eligible.length === 0 && plainPoints.length === 0
    const sourcesUnavailable = sourcesQuery.isLoading ? 'loading' : sourcesQuery.isError ? 'error' : undefined

    return (
        <>
            {sourcesQuery.isError && <div className="error-banner" role="alert">{t('supplementary.section.loadError')}</div>}

            {isEmpty && (
                <div className="card">
                    <h3 style={{ marginTop: 0 }}>{t('pages.myMeteringPoints.empty.title')}</h3>
                    <p className="muted" style={{ marginBottom: 0 }}>
                        {t(isParticipantScope ? 'pages.myMeteringPoints.empty.participant' : 'pages.myMeteringPoints.empty.manager')}
                    </p>
                </div>
            )}

            {energyData.featureOn && eligible.length > 0 && (
                <p className="muted" style={{ margin: 0 }}>{t('supplementary.section.description')}</p>
            )}

            {eligible.map((point) => (
                <MeteringPointEnergyData
                    key={point.metering_point}
                    point={point}
                    source={sources.find((candidate) => candidate.metering_point === point.metering_point)}
                    sourcesUnavailable={sourcesUnavailable}
                    onRetrySources={() => void sourcesQuery.refetch()}
                    confirm={confirm}
                />
            ))}

            {plainPoints.map((point) => (
                <PlainMeteringPoint key={point.id} point={point} showEnergyDataNote={energyData.featureOn} />
            ))}

            {/* Only while the feature is on: with it off the page says nothing about energy data. */}
            {energyData.featureOn && isParticipantScope && !isEmpty && (
                <p className="muted">{t('pages.myMeteringPoints.flagHint')}</p>
            )}

            {dialog && <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </>
    )
}

/** A meter of the participant's that has no energy data to set up. */
function PlainMeteringPoint({ point, showEnergyDataNote }: { point: MeteringPoint; showEnergyDataNote: boolean }) {
    const { t } = useTranslation()
    return (
        <article className="card" style={{ display: 'grid', gap: '0.5rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
            <div>
                <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                <small className="muted">{point.location_description || t('pages.meteringPoints.noLocation')}</small>
            </div>
            <div className="metering-point-badges">
                <span className={point.is_active ? 'badge badge-success' : 'badge badge-danger'}>
                    {point.is_active ? t('pages.meteringPoints.active') : t('pages.meteringPoints.inactive')}
                </span>
                <span className="badge badge-neutral">{t(`pages.meteringPoints.meterTypes.${point.meter_type}`)}</span>
                {point.has_behind_meter_generation && <BehindMeterBadge />}
            </div>
            {showEnergyDataNote && point.has_behind_meter_generation && (
                <p className="muted" style={{ margin: 0 }}>{t('pages.myMeteringPoints.notHolder')}</p>
            )}
            <div className="actions-row actions-row-wrap">
                <MeteringDataLink meteringPointId={point.id} />
            </div>
        </article>
    )
}
