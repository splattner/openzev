import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ConfirmDialog, useConfirmDialog } from '../../components/ConfirmDialog'
import { listSupplementarySources } from '../../lib/api/supplementary'
import { queryKeys } from '../../lib/api/queryKeys'
import { useEnergyDataEligibility } from '../../lib/supplementary'
import type { EligibleMeteringPoint } from '../../types/api'
import { SupplementarySourceCard } from './SupplementarySourceCard'
import { SupplementarySourceModal } from './SupplementarySourceModal'

/**
 * The participant's own energy data: connect Solar Manager or a push/file source to each metering
 * point that has generation behind the meter, and see how it is doing. The figures are only used
 * for statistics, never for billing.
 */
export function EnergyDataSection() {
    const { t } = useTranslation()
    const { eligible, isLoading } = useEnergyDataEligibility()
    const sourcesQuery = useQuery({
        queryKey: queryKeys.metering.supplementarySources(),
        queryFn: listSupplementarySources,
    })
    const [connecting, setConnecting] = useState<EligibleMeteringPoint | null>(null)
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const sources = sourcesQuery.data ?? []

    return (
        <div className="card" style={{ display: 'grid', gap: '1.25rem', gridTemplateColumns: 'minmax(0, 1fr)' }}>
            <div>
                <h2>{t('supplementary.section.title')}</h2>
                <p className="muted" style={{ margin: 0 }}>{t('supplementary.section.description')}</p>
            </div>

            {(isLoading || sourcesQuery.isLoading) && <p className="muted">{t('common.loading')}</p>}
            {sourcesQuery.isError && <div className="error-banner" role="alert">{t('supplementary.section.loadError')}</div>}

            {eligible.map((point) => {
                const source = sources.find((candidate) => candidate.metering_point === point.metering_point)
                if (source) {
                    return <SupplementarySourceCard key={point.metering_point} point={point} source={source} confirm={confirm} />
                }
                return (
                    <article key={point.metering_point} className="card" style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'minmax(0, 1fr)' }} aria-label={point.meter_id}>
                        <div>
                            <h3 style={{ margin: 0, overflowWrap: 'anywhere' }}>{point.meter_id}</h3>
                            <small className="muted">{point.zev_name}</small>
                        </div>
                        <p className="muted" style={{ margin: 0 }}>{t('supplementary.section.notConnected')}</p>
                        <div className="actions-row actions-row-wrap">
                            <button type="button" className="button button-primary" onClick={() => setConnecting(point)}>
                                {t('supplementary.section.connect')}
                            </button>
                        </div>
                    </article>
                )
            })}

            {connecting && <SupplementarySourceModal point={connecting} onClose={() => setConnecting(null)} />}
            {dialog && <ConfirmDialog {...dialog} isLoading={dialogLoading} onConfirm={handleConfirm} onCancel={handleCancel} />}
        </div>
    )
}
