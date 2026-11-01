import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { forecastEligible, historyEligible, liveEligible } from '../../lib/supplementary'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'
import { LiveStateBadge } from './LiveStateBadge'
import { SourceDialog, type ConfirmOptions } from './SourceDialog'
import { SourceStatusBadge } from './SourceStatusBadge'

interface Props {
    /** The signed-in user's visible sources, loaded. */
    sources: SupplementarySource[]
    /** The metering points the user holds personally in the selected community. */
    held: EligibleMeteringPoint[]
    confirm: (options: ConfirmOptions) => void
}

/** The metering points a source feeds. Always one today; a list so a connection feeding several fits. */
const fedMeters = (source: SupplementarySource): string[] => (source.metering_point_meter_id ? [source.metering_point_meter_id] : [])

/**
 * The energy data sources the signed-in holder owns, in one place (SPEC-2026-live-energy-data §7.2): who
 * provides what and how it is doing, with the source dialog behind a button. Only participant-held
 * sources on held meters; connecting stays on the meter cards below.
 */
export function MyConnections({ sources, held, confirm }: Props) {
    const { t } = useTranslation()
    const [openSourceId, setOpenSourceId] = useState<string | null>(null)
    const heldById = new Map(held.map((point) => [point.metering_point, point]))
    const own = sources.filter((source) => source.held_by === 'participant' && source.metering_point !== null && heldById.has(source.metering_point))
    const openSource = own.find((source) => source.id === openSourceId)
    const openPoint = openSource?.metering_point ? heldById.get(openSource.metering_point) : undefined

    return (
        <section className="card" aria-labelledby="my-connections-title">
            <h3 id="my-connections-title" className="mt-0">{t('pages.myMeteringPoints.connections.title')}</h3>
            {own.length === 0 ? (
                <p className="muted m-0">{t('pages.myMeteringPoints.connections.empty')}</p>
            ) : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.75rem' }}>
                    {own.map((source) => {
                        const name = `${t(`supplementary.provider.${source.provider}`)}${source.label ? ` · ${source.label}` : ''}`
                        return (
                            <li
                                key={source.id}
                                data-source={source.id}
                                style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem 1rem', alignItems: 'center', justifyContent: 'space-between' }}
                            >
                                <div style={{ minWidth: 0, flex: '1 1 14rem', display: 'grid', gap: '0.25rem' }}>
                                    <strong style={{ overflowWrap: 'anywhere' }}>{name}</strong>
                                    <ul className="actions-row actions-row-wrap" aria-label={t('pages.myMeteringPoints.connections.meters')} style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                                        {fedMeters(source).map((meter) => (
                                            <li key={meter}><small className="muted" style={{ overflowWrap: 'anywhere' }}>{meter}</small></li>
                                        ))}
                                    </ul>
                                </div>
                                <div className="actions-row actions-row-wrap">
                                    {source.provides_history && (
                                        <>
                                            <span className="badge badge-neutral">{t('supplementary.capability.history')}</span>
                                            <SourceStatusBadge status={source.enabled ? source.status : 'disabled'} />
                                        </>
                                    )}
                                    {source.provides_live && (
                                        <>
                                            <span className="badge badge-neutral">{t('supplementary.capability.live')}</span>
                                            {source.live_state ? <LiveStateBadge state={source.live_state} /> : null}
                                        </>
                                    )}
                                    {source.provides_forecast && (
                                        <>
                                            <span className="badge badge-neutral">{t('supplementary.capability.forecast')}</span>
                                            {/* One status per source: the history chip already carries it. */}
                                            {!source.provides_history && <SourceStatusBadge status={source.enabled ? source.status : 'disabled'} />}
                                        </>
                                    )}
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        aria-label={t('pages.myMeteringPoints.connections.openFor', { name })}
                                        onClick={() => setOpenSourceId(source.id)}
                                    >
                                        {t('pages.myMeteringPoints.connections.open')}
                                    </button>
                                </div>
                            </li>
                        )
                    })}
                </ul>
            )}
            {openSource && (
                <SourceDialog
                    subject={fedMeters(openSource).join(', ')}
                    source={openSource}
                    sources={sources}
                    eligible={openPoint ? { history: historyEligible(openPoint), live: liveEligible(openPoint), forecast: forecastEligible(openPoint) } : undefined}
                    confirm={confirm}
                    canManage
                    onClose={() => setOpenSourceId(null)}
                />
            )}
        </section>
    )
}
