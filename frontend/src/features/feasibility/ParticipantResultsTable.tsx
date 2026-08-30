import { useTranslation } from 'react-i18next'
import type { FeasibilityParticipantResult } from '../../types/api'
import { formatChf, formatKwh } from '../../lib/numbers'

type Props = {
    participants: FeasibilityParticipantResult[]
}

export function ParticipantResultsTable({ participants }: Props) {
    const { t } = useTranslation()
    if (participants.length === 0) return null

    return (
        <div className="table-scroll">
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                <thead>
                    <tr style={{ borderBottom: '1px solid var(--border-default)' }}>
                        <th style={{ textAlign: 'left', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.results.participantName')}</th>
                        <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.results.participantProduction')}</th>
                        <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.results.participantConsumption')}</th>
                        <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.chart.producerGain')}</th>
                        <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.chart.consumerSavingsShort')}</th>
                        <th style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{t('pages.feasibility.results.netBenefit')}</th>
                    </tr>
                </thead>
                <tbody>
                    {participants.map((p) => (
                        <tr key={p.name} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                            <td style={{ padding: '0.4rem 0.6rem' }}>{p.name}</td>
                            <td style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{formatKwh(Number(p.annual_production_kwh), { maxDecimals: 0 })} kWh</td>
                            <td style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{formatKwh(Number(p.annual_consumption_kwh), { maxDecimals: 0 })} kWh</td>
                            <td style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{formatChf(Number(p.producer_gain_chf))}</td>
                            <td style={{ textAlign: 'right', padding: '0.4rem 0.6rem' }}>{formatChf(Number(p.consumer_savings_chf))}</td>
                            <td style={{ textAlign: 'right', padding: '0.4rem 0.6rem', fontWeight: 600 }}>{formatChf(Number(p.net_benefit_chf))}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}
