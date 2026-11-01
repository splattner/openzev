import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/PageHeader'
import { PageSkeleton } from '../components/PageSkeleton'
import { ScopeGuard } from '../components/ScopeGuard'
import { MyConnections } from '../features/supplementary/MyConnections'
import { MeterDataBand } from '../features/supplementary/MeterDataBand'
import { MeteringPointDataCard } from '../features/supplementary/MeteringPointDataCard'
import { SourcePane } from '../features/supplementary/SourceDialog'
import { useSelectedSourceId, useSourcePane } from '../features/supplementary/useSourcePane'
import { queryKeys } from '../lib/api/queryKeys'
import { listSupplementarySources } from '../lib/api/supplementary'
import { fetchMeteringPoints } from '../lib/api/zev'
import { useCommunityAccess, useScopeNote } from '../lib/communityAccess'
import { useManagedZev } from '../lib/managedZev'
import { selectedCommunityName } from '../lib/membership'
import { forecastEligible, hasCapability, historyEligible, liveEligible, useEnergyDataEligibility } from '../lib/supplementary'
import type { MeteringPoint } from '../types/api'

/** Content width from which the cards and the source pane sit side by side; below it the pane takes the area. */
const SPLIT_MIN_REM = 60


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

    const selectedSourceId = useSelectedSourceId()

    // With the live flag on the list holds every held meter: a point is set up here only for a
    // capability it has (history behind the meter, live anywhere active); the rest stays plain.
    const eligible = energyData.eligible.filter((point) => point.zev === selectedZevId && hasCapability(point))
    const eligibleByPoint = new Map(eligible.map((point) => [point.metering_point, point]))
    // The key is shared with the metering points page, so a disabled query can still hold the
    // community's whole list from a visit there: only a participant's own list is used.
    const ownPoints = isParticipantScope ? (pointsQuery.data ?? []) : []
    const plainPoints = ownPoints.filter((point) => !eligibleByPoint.has(point.id))

    const heldPoints = energyData.eligible.filter((point) => point.zev === selectedZevId)
    const heldById = new Map(heldPoints.map((point) => [point.metering_point, point]))
    // Only a participant-held source on a meter the user holds opens here (the list says which).
    const selectedSource = sourcesQuery.data?.find(
        (source) => source.id === selectedSourceId && source.held_by === 'participant' && !!source.metering_point && heldById.has(source.metering_point),
    )
    const selectedPoint = selectedSource?.metering_point ? heldById.get(selectedSource.metering_point) : undefined
    // The source open beside the cards (SPEC-2026-10-ui-patterns §6.2); its id lives in the URL.
    const { splitRef, fitsTwoPanes, listHidden, paneTitleRef, setPaneDirty, openSource, closePane } = useSourcePane({
        splitMinRem: SPLIT_MIN_REM, confirm, selectedSourceId, paneOpen: !!selectedSource,
    })

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
    const hasConnection = (sourcesQuery.data ?? []).some(
        (source) => source.held_by === 'participant' && source.metering_point !== null && eligibleByPoint.has(source.metering_point),
    )
    const sourcesUnavailable = sourcesQuery.isLoading ? 'loading' : sourcesQuery.isError ? 'error' : undefined

    return (
        <>
            <div
                ref={splitRef}
                className="detail-split"
                data-layout={fitsTwoPanes ? 'wide' : 'narrow'}
                data-pane={selectedSource ? 'open' : 'closed'}
            >
                <div className="detail-split-list page-stack" hidden={listHidden}>
                    {sourcesQuery.isError && <div className="error-banner" role="alert">{t('supplementary.section.loadError')}</div>}

                    {isEmpty && (
                        <div className="card">
                            <h3 className="mt-0">{t('pages.myMeteringPoints.empty.title')}</h3>
                            <p className="muted" style={{ marginBottom: 0 }}>
                                {t(isParticipantScope ? 'pages.myMeteringPoints.empty.participant' : 'pages.myMeteringPoints.empty.manager')}
                            </p>
                        </div>
                    )}

                    {energyData.featureOn && sourcesQuery.data && (
                        <MyConnections
                            sources={sourcesQuery.data}
                            held={heldPoints}
                            onOpenSource={openSource}
                            selectedSourceId={selectedSourceId}
                        />
                    )}

                    {eligible.map((point) => (
                        <MeteringPointDataCard
                            key={point.metering_point}
                            point={point}
                            description={ownPoints.find((own) => own.id === point.metering_point)?.location_description || undefined}
                            sources={sourcesQuery.data}
                            sourcesUnavailable={sourcesUnavailable}
                            onRetrySources={() => void sourcesQuery.refetch()}
                            onOpenSource={openSource}
                            selectedSourceId={selectedSourceId}
                            onConnected={openSource}
                        />
                    ))}

                    {plainPoints.map((point) => (
                        <PlainMeteringPoint key={point.id} point={point} showEnergyDataNote={energyData.featureOn} />
                    ))}

                    {/* Only while the feature is on (with it off the page says nothing about energy data), and only for someone who has not got an own system connected or flagged yet. */}
                    {energyData.featureOn && isParticipantScope && !isEmpty && !eligible.some(historyEligible) && !hasConnection && (
                        <p className="muted">{t('pages.myMeteringPoints.flagHint')}</p>
                    )}
                </div>

                {selectedSource && selectedPoint && (
                    <SourcePane
                        key={selectedSource.id}
                        subject={selectedPoint.meter_id}
                        source={selectedSource}
                        sources={sourcesQuery.data}
                        eligible={{ history: historyEligible(selectedPoint), live: liveEligible(selectedPoint), forecast: forecastEligible(selectedPoint) }}
                        confirm={confirm}
                        canManage
                        titleRef={paneTitleRef}
                        onDirtyChange={setPaneDirty}
                        onClose={closePane}
                    />
                )}
            </div>

            {dialog && <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </>
    )
}

/** A meter of the participant's that has no energy data to set up. */
function PlainMeteringPoint({ point, showEnergyDataNote }: { point: MeteringPoint; showEnergyDataNote: boolean }) {
    const { t } = useTranslation()
    // What the meter is is quiet text (UI patterns §10.1); only a meter that is switched off is worth saying.
    const facts = [
        point.location_description || t('pages.meteringPoints.noLocation'),
        t(`pages.meteringPoints.meterTypes.${point.meter_type}`),
        point.has_behind_meter_generation ? t('behindMeter.badge') : null,
        point.is_active ? null : t('pages.meteringPoints.inactive'),
    ].filter(Boolean).join(' · ')
    return (
        <article className="card" style={{ display: 'grid', gap: '0.5rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
            <header className="card-title-block">
                <h3>{point.meter_id}</h3>
                <small className="muted">{facts}</small>
            </header>
            <MeterDataBand meteringPointId={point.id} />
            {showEnergyDataNote && point.has_behind_meter_generation && (
                <p className="muted m-0">{t('pages.myMeteringPoints.notHolder')}</p>
            )}
        </article>
    )
}
