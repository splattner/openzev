import { useTranslation } from 'react-i18next'
import { capabilityProblem } from '../../lib/supplementary'
import { CapabilityProblemText } from './CapabilityProblemText'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'

interface Props {
    /** The signed-in user's visible sources, loaded. */
    sources: SupplementarySource[]
    /** The metering points the user holds personally in the selected community. */
    held: EligibleMeteringPoint[]
    /** Open the source's details beside the list. */
    onOpenSource: (source: SupplementarySource) => void
    selectedSourceId?: string | null
}

/** The metering points a source feeds. Always one today; a list so a connection feeding several fits. */
const fedMeters = (source: SupplementarySource): string[] => (source.metering_point_meter_id ? [source.metering_point_meter_id] : [])

/**
 * The energy data sources the signed-in holder owns, in one place (SPEC-2026-live-energy-data §7.2): who
 * provides what, with a problem named next to the capability it concerns and the source dialog behind a
 * button (the details open beside the page's cards). Only from two sources on: one is all on its meter's card. Only participant-held sources on held
 * meters; connecting stays on the meter cards below.
 */
export function MyConnections({ sources, held, onOpenSource, selectedSourceId }: Props) {
    const { t } = useTranslation()
    const heldById = new Map(held.map((point) => [point.metering_point, point]))
    const own = sources.filter((source) => source.held_by === 'participant' && source.metering_point !== null && heldById.has(source.metering_point))

    // One connection is already on its meter's card below; the overview is for telling several apart.
    if (own.length < 2) return null

    return (
        <section className="card" aria-labelledby="my-connections-title">
            <h3 id="my-connections-title" className="mt-0">{t('pages.myMeteringPoints.connections.title')}</h3>
            <ul className="connection-list">
                {own.map((source) => {
                    const name = `${t(`supplementary.provider.${source.provider}`)}${source.label ? ` · ${source.label}` : ''}`
                    const capabilities = (['history', 'live', 'forecast'] as const).filter((capability) => source[`provides_${capability}`])
                    return (
                        <li key={source.id} data-source={source.id} className="connection-row">
                            <div className="connection-main">
                                <strong className="connection-name">{name}</strong>
                                <ul className="actions-row actions-row-wrap connection-meters" aria-label={t('pages.myMeteringPoints.connections.meters')}>
                                    {fedMeters(source).map((meter) => (
                                        <li key={meter}><small className="muted connection-name">{meter}</small></li>
                                    ))}
                                </ul>
                            </div>
                            <div className="actions-row actions-row-wrap">
                                {capabilities.map((capability) => {
                                    const problem = capabilityProblem(source, capability)
                                    return (
                                        <span key={capability} className="connection-capability">
                                            <span className="badge badge-tag">{t(`supplementary.capability.${capability}`)}</span>
                                            <CapabilityProblemText problem={problem} />
                                        </span>
                                    )
                                })}
                                <button
                                    type="button"
                                    className="button button-secondary button-compact"
                                    aria-label={t('pages.myMeteringPoints.connections.openFor', { name })}
                                    data-source-open={source.id}
                                    aria-current={source.id === selectedSourceId ? 'true' : undefined}
                                    onClick={() => onOpenSource(source)}
                                >
                                    {t('pages.myMeteringPoints.connections.open')}
                                </button>
                            </div>
                        </li>
                    )
                })}
            </ul>
        </section>
    )
}
