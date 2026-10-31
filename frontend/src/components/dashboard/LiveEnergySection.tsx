import { liveCardState, useLiveCurve, useLiveEnergy } from '../../lib/live'
import { LiveCurveChart } from './LiveCurveChart'
import { LiveEnergyCard } from './LiveEnergyCard'
import { LivePointsTable } from './LivePointsTable'

/**
 * The live part of a dashboard: "now" for one ZEV, independent of the period selected below it.
 * Renders nothing while the feature is off, the caller may not see the ZEV or no live source exists.
 */
export function LiveEnergySection({ zevId }: { zevId: string | undefined }) {
    const snapshot = useLiveEnergy(zevId).data
    const state = liveCardState(snapshot)
    const curve = useLiveCurve(zevId, !!state).data
    if (!snapshot || !state) return null
    return (
        <>
            <LiveEnergyCard snapshot={snapshot} />
            {curve && <LiveCurveChart curve={curve} />}
            {snapshot.points && snapshot.points.length > 0 && <LivePointsTable points={snapshot.points} />}
        </>
    )
}
