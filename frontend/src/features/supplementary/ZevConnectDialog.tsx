import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import { FormModalCancelButton } from '../../components/FormModalFooter'
import { useAuth } from '../../lib/auth'
import type { SourceCapability, SupplementarySource, ZevEligibleSources } from '../../types/api'
import { CapabilityRows, type RowCapability } from './CapabilityRows'
import { ForecastConnectDialog } from './ForecastConnectDialog'
import { SupplementarySourceModal } from './SupplementarySourceModal'

const CONNECTION_POINT = 'connection-point'
const ZEV_CAPABILITIES: SourceCapability[] = ['live', 'forecast']

interface Props {
    zevId: string
    eligibility: ZevEligibleSources
    sources: SupplementarySource[] | undefined
    onClose: () => void
    /** A source was connected from this dialog; the host opens it. */
    onConnected: (source: SupplementarySource) => void
    /** Open a source that is already connected (a row of the chosen meter). */
    onOpenSource: (source: SupplementarySource) => void
}

/** What a manager can still connect for the community: a meter nobody holds (live, forecast) or the grid connection point. */
export function connectableTargets(eligibility: ZevEligibleSources | undefined) {
    const meters = (eligibility?.metering_points ?? [])
        .map((entry) => ({ ...entry, missing: ZEV_CAPABILITIES.filter((capability) => entry.eligible_capabilities.includes(capability) && entry.sources[capability] === null) }))
        .filter((entry) => entry.missing.length > 0)
    const connection = !!eligibility?.connection_point.available && !eligibility.connection_point.source
    return { meters, connection, any: meters.length > 0 || connection }
}

/**
 * Connect a source for the community: choose what it reports on (a meter nobody holds personally, or the grid
 * connection point), then connect each thing that meter can provide. A participant's own meters are connected by the
 * participant, on My metering points. The connect flows are the ones the metering-point page used to open.
 */
export function ZevConnectDialog({ zevId, eligibility, sources, onClose, onConnected, onOpenSource }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const targets = connectableTargets(eligibility)
    const [target, setTarget] = useState(() => (targets.meters.length + (targets.connection ? 1 : 0) === 1 ? (targets.connection ? CONNECTION_POINT : targets.meters[0].metering_point) : ''))
    const [flow, setFlow] = useState<'connect' | 'forecast' | null>(null)

    const meter = targets.meters.find((entry) => entry.metering_point === target)
    // A meter that already has a source keeps its rows here, so a missing forecast can be added next to a live source.
    const entry = eligibility.metering_points.find((candidate) => candidate.metering_point === target)
    const point = entry ? { metering_point: entry.metering_point, meter_id: entry.meter_id, zev: zevId } : undefined

    if (flow === 'connect' && target === CONNECTION_POINT) {
        return <SupplementarySourceModal holder="connection-point" zevId={zevId} onClose={() => setFlow(null)} onConnected={(source) => { onClose(); onConnected(source) }} />
    }
    if (flow === 'connect' && point) {
        return <SupplementarySourceModal holder="zev" point={point} sources={sources} onClose={() => setFlow(null)} onConnected={(source) => { onClose(); onConnected(source) }} />
    }
    if (flow === 'forecast' && point) {
        return <ForecastConnectDialog holder="zev" point={point} onClose={() => setFlow(null)} onConnected={(source) => { onClose(); onConnected(source) }} />
    }

    const capabilities = (meter ? meter.missing : []) as RowCapability[]
    return (
        <FormModal isOpen size="md" title={t('supplementary.zev.connectTitle')} onClose={onClose}>
            <div className="dialog-stack">
                <label>
                    <span>{t('supplementary.zev.target')}</span>
                    <select value={target} onChange={(event) => setTarget(event.target.value)}>
                        {!target && <option value="">{t('supplementary.zev.pickTarget')}</option>}
                        {targets.connection && <option value={CONNECTION_POINT}>{t('live.points.connection')}</option>}
                        {targets.meters.map((candidate) => (
                            <option key={candidate.metering_point} value={candidate.metering_point}>
                                {candidate.meter_id} · {candidate.missing.map((capability) => t(`supplementary.capability.${capability}`)).join(', ')}
                            </option>
                        ))}
                    </select>
                </label>
                {!target && <p className="muted m-0">{t('supplementary.zev.pickHint')}</p>}
                {target === CONNECTION_POINT && (
                    <>
                        <p className="muted m-0">{t('supplementary.connection.description')}</p>
                        <div className="actions-row actions-row-wrap">
                            <button
                                type="button"
                                className="button button-primary"
                                disabled={isImpersonating}
                                title={isImpersonating ? t('account.impersonationRestrictions') : undefined}
                                onClick={() => setFlow('connect')}
                            >
                                {t('supplementary.connection.connect')}
                            </button>
                        </div>
                    </>
                )}
                {meter && (
                    <CapabilityRows
                        meteringPointId={meter.metering_point}
                        capabilities={capabilities}
                        sources={sources}
                        zevHeld
                        onOpenSource={(source) => { onClose(); onOpenSource(source) }}
                        onConnect={(capability) => setFlow(capability === 'forecast' ? 'forecast' : 'connect')}
                    />
                )}
                <div className="actions-row actions-row-wrap">
                    <FormModalCancelButton onCancel={onClose} />
                </div>
            </div>
        </FormModal>
    )
}
