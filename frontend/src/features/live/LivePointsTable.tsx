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
            <div className="table-scroll live-points-wide">
                <table className="participant-table live-points-table">
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
            {/* On a phone the columns would hide the one thing the table is for (the kW), so each point is a small card. */}
            <ul className="live-points-list">
                {points.map((point) => (
                    <li key={point.source_id ?? point.metering_point_id ?? point.target}>
                        <div className="live-points-list-head">
                            <strong>{point.target === 'connection_point' ? t('live.points.connection') : point.meter_id}</strong>
                            <LiveStateBadge state={point.live_state} />
                        </div>
                        <span className="muted">{point.participant_name ?? t('live.points.zevOperated')}</span>
                        {point.meter_power_w !== null && (
                            <span>
                                {formatKw(point.meter_power_w)}
                                {point.age_s !== null && ` · ${t('live.points.seconds', { count: point.age_s })}`}
                            </span>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    )
}
