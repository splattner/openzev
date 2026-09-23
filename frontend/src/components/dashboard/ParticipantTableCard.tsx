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
            <h3 style={{ marginTop: 0 }}>{t('pages.dashboard.perParticipant')}</h3>
            {participantStats.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noParticipantData')}</p>
            ) : (
                <div className="table-scroll">
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr>
                                <th style={{ textAlign: 'left', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.participant')}</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.consumption')}</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.productionExport')}</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.fromZev')}</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.fromGrid')}</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }}>{t('pages.dashboard.col.fromZevPercent')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {participantStats.map((participant) => (
                                <tr
                                    key={participant.participant_id}
                                    onClick={() => onSelect(participant.participant_id)}
                                    style={{
                                        borderTop: '1px solid var(--border-default)',
                                        cursor: 'pointer',
                                        backgroundColor: selectedParticipantId === participant.participant_id ? 'var(--surface)' : 'transparent',
                                        transition: 'background-color 150ms ease-in-out',
                                    }}
                                    onMouseEnter={(e) => {
                                        if (selectedParticipantId !== participant.participant_id) {
                                            e.currentTarget.style.backgroundColor = 'var(--surface)'
                                        }
                                    }}
                                    onMouseLeave={(e) => {
                                        if (selectedParticipantId !== participant.participant_id) {
                                            e.currentTarget.style.backgroundColor = 'transparent'
                                        }
                                    }}
                                >
                                    <td style={{ padding: '0.5rem 0.6rem' }}>{participant.participant_name || '-'}</td>
                                    <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }} className="numeric">{dashboardKwhStat(participant.total_consumed_kwh)}</td>
                                    <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }} className="numeric">{dashboardKwhStat(participant.total_produced_kwh)}</td>
                                    <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }} className="numeric">{dashboardKwhStat(participant.from_zev_kwh)}</td>
                                    <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }} className="numeric">{dashboardKwhStat(participant.from_grid_kwh)}</td>
                                    <td style={{ textAlign: 'right', padding: '0.5rem 0.6rem' }} className="numeric">{formatPercent(zevSharePercent(participant))}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    )
}
