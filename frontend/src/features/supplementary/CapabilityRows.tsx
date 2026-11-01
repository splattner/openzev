import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { capabilityProblem, sourceFor } from '../../lib/supplementary'
import type { SupplementarySource } from '../../types/api'
import { CapabilityProblemText } from './CapabilityProblemText'

export type RowCapability = 'history' | 'live' | 'forecast'

interface Props {
    meteringPointId: string
    /** One row per capability the point is eligible for. */
    capabilities: RowCapability[]
    sources: SupplementarySource[] | undefined
    /** The caller may connect and change sources; a viewer only reads. */
    canManage?: boolean
    onOpenSource: (source: SupplementarySource) => void
    /** The source whose details are open beside the list, to be marked. */
    selectedSourceId?: string | null
    onConnect: (capability: RowCapability) => void
    /** Wording of an unconnected live row on a ZEV-operated meter. */
    zevHeld?: boolean
}

/**
 * What a metering point provides, one row per capability: the source that provides it as a button that
 * opens the source (a source providing both is in both rows and opens the same details) and what, if
 * anything, is wrong with it, or "Not connected" with a Connect for that capability.
 */
export function CapabilityRows({ meteringPointId, capabilities, sources, canManage = true, onOpenSource, selectedSourceId, onConnect, zevHeld = false }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))

    return (
        <ul className="capability-list">
            {capabilities.map((capability) => {
                const source = sourceFor(sources, meteringPointId, capability)
                return (
                    <li key={capability} data-capability={capability} className="capability-row">
                        <strong className="capability-label">{t(`supplementary.capability.${capability}`)}</strong>
                        <div className="actions-row actions-row-wrap capability-body">
                            {source ? (
                                <>
                                    <button
                                        type="button"
                                        className="button button-ghost button-compact capability-source"
                                        data-source-open={source.id}
                                        aria-current={source.id === selectedSourceId ? 'true' : undefined}
                                        onClick={() => onOpenSource(source)}
                                    >
                                        {t(`supplementary.provider.${source.provider}`)}
                                        {source.label ? ` · ${source.label}` : ''}
                                    </button>
                                    <CapabilityProblemText problem={capabilityProblem(source, capability)} />
                                    {/* A live source that has never reported says so once, as the problem text. */}
                                    <small className="muted">
                                        {capability === 'live' && source.live_state === 'never' ? null : capability === 'history'
                                            ? (source.synced_through
                                                ? t('supplementary.card.syncedThrough', { date: formatDateTime(source.synced_through, settings) })
                                                : t('supplementary.card.noData'))
                                            : capability === 'forecast'
                                                ? (source.provider === 'forecast_solar'
                                                    ? (source.last_success_at
                                                        ? t('supplementary.forecast.updatedAt', { date: formatDateTime(source.last_success_at, settings) })
                                                        : t('supplementary.card.noData'))
                                                    : null)
                                                : t('supplementary.card.lastValueAt', { date: dateTime(source.live_last_seen_at) })}
                                    </small>
                                </>
                            ) : (
                                <>
                                    <span className="muted">{t('supplementary.card.notConnected')}</span>
                                    {canManage && (
                                        <button
                                            type="button"
                                            className="button button-secondary button-compact"
                                            disabled={isImpersonating}
                                            title={isImpersonating ? t('account.impersonationRestrictions') : undefined}
                                            aria-label={t('supplementary.card.connectCapability', { capability: t(`supplementary.capability.${capability}`) })}
                                            onClick={() => onConnect(capability)}
                                        >
                                            {t('supplementary.card.connectRow')}
                                        </button>
                                    )}
                                </>
                            )}
                        </div>
                        {!source && zevHeld && capability === 'live' && <small className="muted capability-note">{t('supplementary.live.zevNotConnected')}</small>}
                        {!source && zevHeld && capability === 'forecast' && <small className="muted capability-note">{t('supplementary.forecast.zevNotConnected')}</small>}
                    </li>
                )
            })}
        </ul>
    )
}
