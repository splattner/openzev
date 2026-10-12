import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { EligibleMeteringPoint, SupplementarySource } from '../../types/api'
import { MeteringDataLink } from './MeteringDataLink'
import { SupplementarySourceCard } from './SupplementarySourceCard'
import { SupplementarySourceModal } from './SupplementarySourceModal'

type ConfirmOptions = {
    title: string
    message: string
    confirmText: string
    isDangerous: boolean
    onConfirm: () => void | Promise<void>
}

interface Props {
    point: EligibleMeteringPoint
    /** The point's source, if one is connected. */
    source: SupplementarySource | undefined
    /** The source list is still loading or failed: a source the point is known to have cannot be shown yet. */
    sourcesUnavailable?: 'loading' | 'error'
    onRetrySources?: () => void
    confirm: (options: ConfirmOptions) => void
}

/**
 * The energy data of one metering point with generation behind the meter, for the participant
 * who holds it: connect Solar Manager or a push/file source, or see how the connected one is
 * doing. The figures are only used for statistics, never for billing.
 */
export function MeteringPointEnergyData({ point, source, sourcesUnavailable, onRetrySources, confirm }: Props) {
    const { t } = useTranslation()
    const [connecting, setConnecting] = useState(false)

    // The modal is rendered next to whichever card shows, never inside one: creating a source makes
    // the connected card replace the "not connected" one while a push source's one-time token is
    // still on screen, and the modal's state has to survive that.
    const modal = connecting ? <SupplementarySourceModal point={point} onClose={() => setConnecting(false)} /> : null

    let card
    if (source) {
        card = <SupplementarySourceCard point={point} source={source} confirm={confirm} />
    } else if (point.source && sourcesUnavailable) {
        // Eligibility says a source exists but its details are not here yet: offering Connect would be wrong.
        card = (
            <article className="card" style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
                <div>
                    <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                    <small className="muted">{point.zev_name}</small>
                </div>
                {sourcesUnavailable === 'loading' ? (
                    <p className="muted" style={{ margin: 0 }}>{t('common.loading')}</p>
                ) : (
                    <div className="error-banner" role="alert">
                        {t('supplementary.section.loadError')}
                        {onRetrySources && (
                            <button type="button" className="button button-secondary button-compact" onClick={onRetrySources} style={{ marginLeft: '0.75rem' }}>
                                {t('common.retry')}
                            </button>
                        )}
                    </div>
                )}
                <div className="actions-row actions-row-wrap">
                    <MeteringDataLink meteringPointId={point.metering_point} />
                </div>
            </article>
        )
    } else {
        card = (
            <article className="card" style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
                <div>
                    <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                    <small className="muted">{point.zev_name}</small>
                </div>
                <p className="muted" style={{ margin: 0 }}>{t('supplementary.section.notConnected')}</p>
                <div className="actions-row actions-row-wrap">
                    <button type="button" className="button button-primary" onClick={() => setConnecting(true)}>
                        {t('supplementary.section.connect')}
                    </button>
                    <MeteringDataLink meteringPointId={point.metering_point} />
                </div>
            </article>
        )
    }

    return (
        <>
            {card}
            {modal}
        </>
    )
}
