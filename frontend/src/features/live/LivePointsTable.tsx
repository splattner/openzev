import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { formatKw } from '../../lib/live'
import type { LivePoint } from '../../types/api'
import { LiveStateBadge } from '../supplementary/LiveStateBadge'

/** Each live source's latest value, for whoever manages or may view the ZEV (the snapshot carries `points` only for them). */
export function LivePointsTable({ points }: { points: LivePoint[] }) {
    const { t } = useTranslation()
    const titleId = useId()
    return (
        <section className="card" aria-labelledby={titleId}>
            <h3 id={titleId}>{t('live.points.title')}</h3>
            <div className="table-scroll">
                <table className="participant-table">
                    <thead>
                        <tr>
                            <th>{t('live.points.meter')}</th>
                            <th>{t('live.points.holder')}</th>
                            <th className="numeric">{t('live.points.power')}</th>
                            <th className="numeric">{t('live.points.age')}</th>
                            <th>{t('live.points.state')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {points.map((point) => (
                            <tr key={point.source_id ?? point.metering_point_id ?? point.target}>
                                <td className="live-meter-cell">{point.target === 'connection_point' ? t('live.points.connection') : point.meter_id}</td>
                                <td>{point.participant_name ?? t('live.points.zevOperated')}</td>
                                <td className="numeric">{point.meter_power_w === null ? '—' : formatKw(point.meter_power_w)}</td>
                                <td className="numeric">{point.age_s === null ? '—' : t('live.points.seconds', { count: point.age_s })}</td>
                                <td><LiveStateBadge state={point.live_state} /></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </section>
    )
}
