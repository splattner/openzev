import { SortableHeader, useTableSorting } from '../../components/tableSorting'
import { useId } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useCommunityAccess } from '../../lib/communityAccess'
import { formatKw, livePointFlow } from '../../lib/live'
import type { LivePoint } from '../../types/api'
import { LiveStateBadge } from '../supplementary/LiveStateBadge'

function pointKey(point: LivePoint) {
    return point.source_id ?? point.metering_point_id ?? point.target
}

/** The meter, or the grid connection, which has none. */
function PointName({ point }: { point: LivePoint }) {
    const { t } = useTranslation()
    return <>{point.target === 'connection_point' ? t('live.points.connection') : point.meter_id}</>
}

/** The power with its direction in words, never the meter's minus sign. */
function usePointPower() {
    const { t } = useTranslation()
    return (point: LivePoint) => {
        if (point.meter_power_w === null) return '—'
        const flow = livePointFlow(point)
        return flow ? t(`live.points.flow.${flow.flow}`, { value: formatKw(flow.watts) }) : formatKw(point.meter_power_w)
    }
}

/** What a point with no source offers next: a manager connects one the community operates, a participant's own is theirs to connect. */
function ConnectNote({ point }: { point: LivePoint }) {
    const { t } = useTranslation()
    const { canManage } = useCommunityAccess()
    if (point.source_id !== null || point.target !== 'metering_point') return null
    if (point.participant_name !== null) return <span className="muted"> · {t('live.points.holderConnects')}</span>
    if (!canManage || !point.meter_id) return null
    return (
        <>
            {' · '}
            <Link className="text-link" to="/zev-settings/energy">{t('live.points.connect')}</Link>
        </>
    )
}

/**
 * Each live source's latest value, for whoever manages or may view the ZEV (the snapshot carries `points` only
 * for them). It is always open: the points without a value are the reason to look, and each says what to do next.
 */
export function LivePointsTable({ points }: { points: LivePoint[] }) {
    const { t } = useTranslation()
    const power = usePointPower()
    const titleId = useId()
    const sorting = useTableSorting(points, {
        meter: row => row.meter_id ?? row.target,
        holder: row => row.participant_name,
        power: row => row.meter_power_w,
        age: row => row.age_s,
        state: row => row.live_state,
    })
    return (
        <section className="card" aria-labelledby={titleId}>
            <div className="card-header">
                <h3 id={titleId}>{t('live.points.summary')}</h3>
            </div>
                <div className="table-scroll live-points-wide">
                    <table className="participant-table live-points-table">
                        <thead>
                            <tr>
                                <SortableHeader {...sorting.header('meter')}>{t('live.points.meter')}</SortableHeader>
                                <SortableHeader {...sorting.header('holder')}>{t('live.points.holder')}</SortableHeader>
                                <SortableHeader {...sorting.header('power')} className="numeric">{t('live.points.power')}</SortableHeader>
                                <SortableHeader {...sorting.header('age')} className="numeric">{t('live.points.age')}</SortableHeader>
                                <SortableHeader {...sorting.header('state')}>{t('live.points.state')}</SortableHeader>
                            </tr>
                        </thead>
                        <tbody>
                            {sorting.rows.map((point) => (
                                <tr key={pointKey(point)}>
                                    <td className="live-meter-cell"><PointName point={point} /></td>
                                    <td>{point.participant_name ?? t('live.points.zevOperated')}</td>
                                    <td className="numeric">{power(point)}</td>
                                    <td className="numeric">{point.age_s === null ? '—' : t('live.points.seconds', { count: point.age_s })}</td>
                                    <td><LiveStateBadge state={point.live_state} /><ConnectNote point={point} /></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {/* On a phone the columns would hide the one thing the table is for (the kW), so each point is a small card. */}
                <ul className="live-points-list">
                    {sorting.rows.map((point) => (
                        <li key={pointKey(point)}>
                            <div className="live-points-list-head">
                                <strong><PointName point={point} /></strong>
                                <span><LiveStateBadge state={point.live_state} /><ConnectNote point={point} /></span>
                            </div>
                            <span className="muted">{point.participant_name ?? t('live.points.zevOperated')}</span>
                            {point.meter_power_w !== null && (
                                <span>
                                    {power(point)}
                                    {point.age_s !== null && ` · ${t('live.points.seconds', { count: point.age_s })}`}
                                </span>
                            )}
                        </li>
                    ))}
                </ul>
        </section>
    )
}
