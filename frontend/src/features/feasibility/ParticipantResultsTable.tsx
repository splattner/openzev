import { SortableHeader, useTableSorting } from '../../components/tableSorting'
import { useTranslation } from 'react-i18next'
import type { FeasibilityParticipantResult } from '../../types/api'
import { formatChf, formatKwh } from '../../lib/numbers'

type Props = {
    participants: FeasibilityParticipantResult[]
}

export function ParticipantResultsTable({ participants }: Props) {
    const { t } = useTranslation()
    const sorting = useTableSorting(participants, {
        participantName: row => row.name,
        participantProduction: row => Number(row.annual_production_kwh),
        participantConsumption: row => Number(row.annual_consumption_kwh),
        producerGain: row => Number(row.producer_gain_chf),
        consumerSavingsShort: row => Number(row.consumer_savings_chf),
        netBenefit: row => Number(row.net_benefit_chf),
    })
    if (participants.length === 0) return null

    return (
        <div className="table-scroll">
            <table className="compact-table feasibility-results-table">
                <thead>
                    <tr>
                        <SortableHeader {...sorting.header('participantName')}>{t('pages.feasibility.results.participantName')}</SortableHeader>
                        <SortableHeader {...sorting.header('participantProduction')}>{t('pages.feasibility.results.participantProduction')}</SortableHeader>
                        <SortableHeader {...sorting.header('participantConsumption')}>{t('pages.feasibility.results.participantConsumption')}</SortableHeader>
                        <SortableHeader {...sorting.header('producerGain')}>{t('pages.feasibility.chart.producerGain')}</SortableHeader>
                        <SortableHeader {...sorting.header('consumerSavingsShort')}>{t('pages.feasibility.chart.consumerSavingsShort')}</SortableHeader>
                        <SortableHeader {...sorting.header('netBenefit')}>{t('pages.feasibility.results.netBenefit')}</SortableHeader>
                    </tr>
                </thead>
                <tbody>
                    {sorting.rows.map((p) => (
                        <tr key={p.name}>
                            <td>{p.name}</td>
                            <td>{formatKwh(Number(p.annual_production_kwh), { maxDecimals: 0 })} kWh</td>
                            <td>{formatKwh(Number(p.annual_consumption_kwh), { maxDecimals: 0 })} kWh</td>
                            <td>{formatChf(Number(p.producer_gain_chf))}</td>
                            <td>{formatChf(Number(p.consumer_savings_chf))}</td>
                            <td>{formatChf(Number(p.net_benefit_chf))}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
