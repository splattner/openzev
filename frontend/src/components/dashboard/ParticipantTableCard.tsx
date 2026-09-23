import { useTranslation } from 'react-i18next'
import { dashboardKwhStat } from '../../lib/dashboardFormatting'
import { formatPercent } from '../../lib/numbers'
import type { ZevOwnerDashboardSummary } from '../../types/api'

type ParticipantRow = ZevOwnerDashboardSummary['participant_stats'][number]

/** Share of a participant's consumption covered by the ZEV rather than the grid. */
function zevSharePercent(participant: ParticipantRow): number {
    return (participant.from_zev_kwh / participant.total_consumed_kwh) * 100
}

interface ParticipantTableCardProps {
    participantStats: ParticipantRow[]
    selectedParticipantId: string
    onSelect: (participantId: string) => void
}

export function ParticipantTableCard({ participantStats, selectedParticipantId, onSelect }: ParticipantTableCardProps) {
    const { t } = useTranslation()
    return (
        <section className="card">
            <h3>{t('pages.dashboard.perParticipant')}</h3>
            {participantStats.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noParticipantData')}</p>
            ) : (
                <div className="table-scroll">
                    <table className="participant-table">
                        <thead>
                            <tr>
                                <th>{t('pages.dashboard.col.participant')}</th>
                                <th className="numeric">{t('pages.dashboard.col.consumption')}</th>
                                <th className="numeric">{t('pages.dashboard.col.productionExport')}</th>
                                <th className="numeric">{t('pages.dashboard.col.fromZev')}</th>
                                <th className="numeric">{t('pages.dashboard.col.fromGrid')}</th>
                                <th className="numeric">{t('pages.dashboard.col.fromZevPercent')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {participantStats.map((participant) => {
                                const isSelected = selectedParticipantId === participant.participant_id
                                return (
                                    <tr
                                        key={participant.participant_id}
                                        className={isSelected ? 'is-selected' : undefined}
                                        onClick={() => onSelect(participant.participant_id)}
                                    >
                                        <td>
                                            <button
                                                type="button"
                                                className="participant-select"
                                                aria-current={isSelected ? 'true' : undefined}
                                                aria-label={t('pages.dashboard.showDetailsFor', { name: participant.participant_name || '-' })}
                                            >
                                                {participant.participant_name || '-'}
                                            </button>
                                        </td>
                                        <td className="numeric">{dashboardKwhStat(participant.total_consumed_kwh)}</td>
                                        <td className="numeric">{dashboardKwhStat(participant.total_produced_kwh)}</td>
                                        <td className="numeric">{dashboardKwhStat(participant.from_zev_kwh)}</td>
                                        <td className="numeric">{dashboardKwhStat(participant.from_grid_kwh)}</td>
                                        <td className="numeric">{formatPercent(zevSharePercent(participant))}</td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    )
}
