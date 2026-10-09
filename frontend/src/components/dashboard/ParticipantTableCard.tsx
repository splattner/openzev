import { useTranslation } from 'react-i18next'
import { BehindMeterBadge } from '../BehindMeterBadge'
import { dashboardKwhStat } from '../../lib/dashboardFormatting'
import { formatPercent } from '../../lib/numbers'
import { behindMeterHintKey } from '../../lib/supplementary'
import { NetMeteredRate } from './NetMeteredRate'
import { OwnSystemKwh } from './OwnSystemKwh'
import type { ZevOwnerDashboardSummary } from '../../types/api'

type ParticipantRow = ZevOwnerDashboardSummary['participant_stats'][number]

/** Share of a participant's consumption covered by the ZEV rather than the grid. */
function zevSharePercent(participant: ParticipantRow): number {
    return (participant.from_zev_kwh / participant.total_consumed_kwh) * 100
}

interface ParticipantTableCardProps {
    participantStats: ParticipantRow[]
    selectedParticipantId: string
    /** Selecting the selected row again clears the selection (an empty id). */
    onSelect: (participantId: string) => void
    /** The signed-in user's own participant rows, marked in the table. */
    ownParticipantIds?: string[]
}

export function ParticipantTableCard({
    participantStats,
    selectedParticipantId,
    onSelect,
    ownParticipantIds = [],
}: ParticipantTableCardProps) {
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
                                        onClick={() => onSelect(isSelected ? '' : participant.participant_id)}
                                    >
                                        <td>
                                            <button
                                                type="button"
                                                className="participant-select"
                                                aria-pressed={isSelected}
                                                aria-current={isSelected ? 'true' : undefined}
                                                aria-label={t('pages.dashboard.showDetailsFor', { name: participant.participant_name || '-' })}
                                            >
                                                {participant.participant_name || '-'}
                                            </button>
                                            {ownParticipantIds.includes(participant.participant_id) && (
                                                <span className="badge badge-info">{t('pages.dashboard.youBadge')}</span>
                                            )}
                                            {participant.has_behind_meter_generation && (
                                                <BehindMeterBadge hintKey={behindMeterHintKey('participant', participant.gross_energy)} />
                                            )}
                                        </td>
                                        <td
                                            className="numeric"
                                            title={participant.has_behind_meter_generation ? t(behindMeterHintKey('participant', participant.gross_energy)) : undefined}
                                        >
                                            {dashboardKwhStat(participant.total_consumed_kwh)}
                                            {participant.has_behind_meter_generation && (
                                                <OwnSystemKwh gross={participant.gross_energy} kind="consumption" />
                                            )}
                                        </td>
                                        <td className="numeric">
                                            {dashboardKwhStat(participant.total_produced_kwh)}
                                            {participant.has_behind_meter_generation && (
                                                <OwnSystemKwh gross={participant.gross_energy} kind="production" />
                                            )}
                                        </td>
                                        <td className="numeric">{dashboardKwhStat(participant.from_zev_kwh)}</td>
                                        <td className="numeric">{dashboardKwhStat(participant.from_grid_kwh)}</td>
                                        <td className="numeric">
                                            {participant.has_behind_meter_generation ? (
                                                <NetMeteredRate gross={participant.gross_energy} />
                                            ) : (
                                                formatPercent(zevSharePercent(participant))
                                            )}
                                        </td>
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
