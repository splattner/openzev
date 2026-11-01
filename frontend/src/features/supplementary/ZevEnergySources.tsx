import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { Notice } from '../../components/Notice'
import { PageSkeleton } from '../../components/PageSkeleton'
import { queryKeys } from '../../lib/api/queryKeys'
import { fetchZevEligibleSources, listSupplementarySources } from '../../lib/api/supplementary'
import { useLiveEnabled } from '../../lib/live'
import { capabilityProblem, forecastEligible, historyEligible, liveEligible, useEnergyDataEligibility } from '../../lib/supplementary'
import type { SupplementarySource } from '../../types/api'
import { CapabilityProblemText } from './CapabilityProblemText'
import { SourcePane } from './SourceDialog'
import { useSelectedSourceId, useSourcePane } from './useSourcePane'
import { connectableTargets, ZevConnectDialog } from './ZevConnectDialog'

/** Content width from which the list and the source pane sit side by side; below it the pane takes the area. */
const SPLIT_MIN_REM = 56

const CAPABILITIES = ['history', 'live', 'forecast'] as const

interface Props {
    zevId: string
    /** A manager (not a viewer) of the community. */
    canManage: boolean
}

/**
 * Every energy data source of the community in one list, with the source beside it (SPEC-2026-live-energy-data §7.3):
 * what a manager has to look after that is not theirs to connect. The community's own sources (a meter nobody holds
 * personally, the grid connection point) are connected here; a participant's source is theirs, and a manager only
 * switches it off, deletes its data or removes it.
 */
export function ZevEnergySources({ zevId, canManage }: Props) {
    const { t } = useTranslation()
    const energyData = useEnergyDataEligibility()
    const liveOn = useLiveEnabled({ enabled: energyData.featureOn }).data === true
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()
    const [connecting, setConnecting] = useState(false)

    const sourcesQuery = useQuery({
        queryKey: queryKeys.metering.supplementarySources(),
        queryFn: listSupplementarySources,
        enabled: energyData.featureOn,
    })
    const eligibilityQuery = useQuery({
        queryKey: queryKeys.metering.supplementaryZevEligible(zevId),
        queryFn: () => fetchZevEligibleSources(zevId),
        enabled: liveOn && canManage,
        retry: false,
    })

    const sources = (sourcesQuery.data ?? [])
        .filter((source) => source.zev === zevId)
        // The grid connection point first, then the meters by id.
        .sort((a, b) => Number(b.target === 'connection_point') - Number(a.target === 'connection_point') || (a.metering_point_meter_id ?? '').localeCompare(b.metering_point_meter_id ?? ''))
    const ownPoints = new Map(energyData.eligible.filter((entry) => entry.zev === zevId).map((entry) => [entry.metering_point, entry]))

    const selectedSourceId = useSelectedSourceId()
    const selected = sources.find((source) => source.id === selectedSourceId)
    const { splitRef, fitsTwoPanes, listHidden, paneTitleRef, setPaneDirty, openSource, closePane } = useSourcePane({
        splitMinRem: SPLIT_MIN_REM, confirm, selectedSourceId, paneOpen: !!selected,
    })

    if (energyData.isLoading || sourcesQuery.isLoading) return <PageSkeleton variant="cardList" />
    if (!energyData.featureOn) return <Notice tone="warning">{t('supplementary.zev.off')}</Notice>
    if (sourcesQuery.isError) {
        return (
            <Notice tone="error" onRetry={() => void sourcesQuery.refetch()} isRetrying={sourcesQuery.isFetching}>
                {t('supplementary.section.loadError')}
            </Notice>
        )
    }

    const targets = connectableTargets(eligibilityQuery.data)
    const canConnect = canManage && liveOn && !!eligibilityQuery.data
    const selectedPoint = selected?.metering_point ? ownPoints.get(selected.metering_point) : undefined
    const sourceName = (source: SupplementarySource) => (source.target === 'connection_point' ? t('live.points.connection') : source.metering_point_meter_id ?? '')
    const holder = (source: SupplementarySource) => (source.held_by === 'zev' ? t('live.points.zevOperated') : source.participant_name ?? '')

    return (
        <section className="page-stack">
            {/* An empty list explains itself once, in the empty state with its own button; the intro and the toolbar button come with the first source. */}
            {sources.length > 0 && (
                <div className="actions-row actions-row-wrap actions-row-between">
                    <p className="muted m-0 energy-sources-intro">{t(canManage ? 'supplementary.zev.description' : 'supplementary.zev.descriptionReadOnly')}</p>
                    {canConnect && (
                        <div className="energy-sources-connect">
                            <button type="button" className="button button-primary" disabled={!targets.any} onClick={() => setConnecting(true)}>
                                {t('supplementary.zev.connect')}
                            </button>
                            {!targets.any && <small className="muted">{t('supplementary.zev.nothingToConnect')}</small>}
                        </div>
                    )}
                </div>
            )}

            <div
                ref={splitRef}
                className="detail-split"
                data-layout={fitsTwoPanes ? 'wide' : 'narrow'}
                data-pane={selected ? 'open' : 'closed'}
            >
                <div className="detail-split-list" hidden={listHidden}>
                    {sources.length === 0 ? (
                        <EmptyState
                            titleKey="supplementary.zev.empty.title"
                            descriptionKey={canConnect ? (targets.any ? 'supplementary.zev.empty.manager' : 'supplementary.zev.empty.nothing') : 'supplementary.zev.empty.other'}
                            actions={canConnect && targets.any ? [{ labelKey: 'supplementary.zev.connect', onClick: () => setConnecting(true) }] : undefined}
                        />
                    ) : (
                        <ul className="source-rows">
                            {sources.map((source) => (
                                <li key={source.id}>
                                    <button
                                        type="button"
                                        className="source-row"
                                        data-source-open={source.id}
                                        aria-current={source.id === selectedSourceId ? 'true' : undefined}
                                        onClick={() => openSource(source)}
                                    >
                                        <span className="source-row-main">
                                            <strong>{sourceName(source)}</strong>
                                            <small className="muted">{holder(source)}</small>
                                        </span>
                                        <span className="source-row-capabilities">
                                            {CAPABILITIES.filter((capability) => source[`provides_${capability}`]).map((capability) => (
                                                <span key={capability} className="connection-capability">
                                                    <span>{t(`supplementary.capability.${capability}`)}</span>
                                                    <CapabilityProblemText problem={capabilityProblem(source, capability)} />
                                                </span>
                                            ))}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {selected && (
                    <SourcePane
                        key={selected.id}
                        subject={sourceName(selected)}
                        source={selected}
                        sources={sourcesQuery.data}
                        eligible={selectedPoint ? { history: historyEligible(selectedPoint), live: liveEligible(selectedPoint), forecast: forecastEligible(selectedPoint) } : undefined}
                        confirm={confirm}
                        canManage={canManage}
                        onBehalfOf={selected.held_by === 'participant' ? { name: selected.participant_name, own: !!selectedPoint } : undefined}
                        titleRef={paneTitleRef}
                        onDirtyChange={setPaneDirty}
                        onClose={closePane}
                    />
                )}
            </div>

            {connecting && eligibilityQuery.data && (
                <ZevConnectDialog
                    zevId={zevId}
                    eligibility={eligibilityQuery.data}
                    sources={sourcesQuery.data}
                    onClose={() => setConnecting(false)}
                    onConnected={openSource}
                    onOpenSource={openSource}
                />
            )}
            {dialog && <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </section>
    )
}
