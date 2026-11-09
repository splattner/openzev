import { createContext, useContext, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { DataTable, type CellContext, type ColumnDef } from '../DataTable'
import { BehindMeterBadge } from '../BehindMeterBadge'
import { dashboardKwhStat } from '../../lib/dashboardFormatting'
import { formatPercent } from '../../lib/numbers'
import { behindMeterHintKey, grossRate } from '../../lib/supplementary'
import { NetMeteredRate } from './NetMeteredRate'
import { OwnSystemKwh } from './OwnSystemKwh'
import type { ZevOwnerDashboardSummary } from '../../types/api'

type ParticipantRow = ZevOwnerDashboardSummary['participant_stats'][number]

/** Share of a participant's consumption covered by the ZEV rather than the grid. */
function zevSharePercent(participant: ParticipantRow): number {
    return (participant.from_zev_kwh / participant.total_consumed_kwh) * 100
}

/** Keep gross-energy shares and missing consumption consistent with the display. */
function zevShareSortValue(participant: ParticipantRow): number | undefined {
    const share = participant.has_behind_meter_generation
        ? grossRate(participant.gross_energy)
        : participant.total_consumed_kwh > 0 ? zevSharePercent(participant) : null
    return share ?? undefined
}

interface ParticipantTableCardProps {
    participantStats: ParticipantRow[]
    selectedParticipantId: string
    /** Selecting the selected row again clears the selection (an empty id). */
    onSelect: (participantId: string) => void
    /** The signed-in user's own participant rows, marked in the table. */
    ownParticipantIds?: string[]
}

const NO_IDS: string[] = []
const ParticipantSelectionContext = createContext({ selectedParticipantId: '', ownParticipantIds: NO_IDS })

function ParticipantNameCell({ row }: CellContext<ParticipantRow, unknown>) {
    const { t } = useTranslation()
    const { selectedParticipantId, ownParticipantIds } = useContext(ParticipantSelectionContext)
    const participant = row.original
    const isSelected = selectedParticipantId === participant.participant_id
    return (
        <>
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
        </>
    )
}

export function ParticipantTableCard({
    participantStats,
    selectedParticipantId,
    onSelect,
    ownParticipantIds = NO_IDS,
}: ParticipantTableCardProps) {
    const { t } = useTranslation()

    const columns = useMemo<ColumnDef<ParticipantRow, unknown>[]>(() => [
        {
            id: 'participant',
            accessorFn: (participant) => participant.participant_name || '',
            header: t('pages.dashboard.col.participant'),
            cell: ParticipantNameCell,
        },
        {
            id: 'consumption',
            accessorFn: (participant) => participant.total_consumed_kwh,
            header: t('pages.dashboard.col.consumption'),
            meta: { numeric: true },
            cell: ({ row }) => {
                const participant = row.original
                return (
                    <span title={participant.has_behind_meter_generation
                        ? t(behindMeterHintKey('participant', participant.gross_energy))
                        : undefined}>
                        {dashboardKwhStat(participant.total_consumed_kwh)}
                        {participant.has_behind_meter_generation && (
                            <OwnSystemKwh gross={participant.gross_energy} kind="consumption" />
                        )}
                    </span>
                )
            },
        },
        {
            id: 'production_export',
            accessorFn: (participant) => participant.total_produced_kwh,
            header: t('pages.dashboard.col.productionExport'),
            meta: { numeric: true },
            cell: ({ row }) => {
                const participant = row.original
                return (
                    <>
                        {dashboardKwhStat(participant.total_produced_kwh)}
                        {participant.has_behind_meter_generation && (
                            <OwnSystemKwh gross={participant.gross_energy} kind="production" />
                        )}
                    </>
                )
            },
        },
        {
            id: 'from_zev',
            accessorFn: (participant) => participant.from_zev_kwh,
            header: t('pages.dashboard.col.fromZev'),
            meta: { numeric: true },
            cell: ({ row }) => dashboardKwhStat(row.original.from_zev_kwh),
        },
        {
            id: 'from_grid',
            accessorFn: (participant) => participant.from_grid_kwh,
            header: t('pages.dashboard.col.fromGrid'),
            meta: { numeric: true },
            cell: ({ row }) => dashboardKwhStat(row.original.from_grid_kwh),
        },
        {
            id: 'from_zev_percent',
            accessorFn: zevShareSortValue,
            sortUndefined: 'last',
            header: t('pages.dashboard.col.fromZevPercent'),
            meta: { numeric: true },
            cell: ({ row }) => {
                const participant = row.original
                return participant.has_behind_meter_generation
                    ? <NetMeteredRate gross={participant.gross_energy} />
                    : formatPercent(zevSharePercent(participant))
            },
        },
    ], [t])

    return (
        <section className="card">
            <h3>{t('pages.dashboard.perParticipant')}</h3>
            {participantStats.length === 0 ? (
                <p className="muted">{t('pages.dashboard.noParticipantData')}</p>
            ) : (
                <ParticipantSelectionContext.Provider value={{ selectedParticipantId, ownParticipantIds }}>
                    <DataTable
                        data={participantStats}
                        columns={columns}
                        getRowId={(participant) => participant.participant_id}
                        tableClassName="participant-table"
                        rowClassName={(participant) =>
                            selectedParticipantId === participant.participant_id ? 'is-selected' : undefined}
                        onRowClick={(participant) =>
                            onSelect(selectedParticipantId === participant.participant_id ? '' : participant.participant_id)}
                    />
                </ParticipantSelectionContext.Provider>
            )}
        </section>
    )
}
