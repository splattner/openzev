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
    confirm: (options: ConfirmOptions) => void
}

/**
 * The energy data of one metering point with generation behind the meter, for the participant
 * who holds it: connect Solar Manager or a push/file source, or see how the connected one is
 * doing. The figures are only used for statistics, never for billing.
 */
export function MeteringPointEnergyData({ point, source, confirm }: Props) {
    const { t } = useTranslation()
    const [connecting, setConnecting] = useState(false)

    if (source) return <SupplementarySourceCard point={point} source={source} confirm={confirm} />

    return (
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
            {connecting && <SupplementarySourceModal point={point} onClose={() => setConnecting(false)} />}
        </article>
    )
}
