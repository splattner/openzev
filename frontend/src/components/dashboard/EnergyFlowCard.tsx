import { useTranslation } from 'react-i18next'
import { EnergyFlowChart } from '../EnergyFlowChart'

interface EnergyFlowCardProps {
    totals: {
        produced_kwh: number
        consumed_kwh: number
        imported_kwh: number
        exported_kwh: number
    }
    participantStats: Array<{
        participant_id: string
        participant_name: string
        total_consumed_kwh: number
        total_produced_kwh: number
        from_zev_kwh: number
        from_grid_kwh: number
    }>
    highlightParticipantId?: string
    zevName?: string
}

export function EnergyFlowCard({ totals, participantStats, highlightParticipantId, zevName }: EnergyFlowCardProps) {
    const { t } = useTranslation()
    if (participantStats.length === 0) return null
    return (
        <section className="card">
            <h3 style={{ marginTop: 0 }}>
                {t('pages.dashboard.energyFlow.title')}
                {zevName ? ` — ${zevName}` : ''}
            </h3>
            <EnergyFlowChart totals={totals} participantStats={participantStats} highlightParticipantId={highlightParticipantId} />
        </section>
    )
}
