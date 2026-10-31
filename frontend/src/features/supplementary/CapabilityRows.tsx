import { useTranslation } from 'react-i18next'
import { useAuth } from '../../lib/auth'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { sourceFor } from '../../lib/supplementary'
import type { SupplementarySource } from '../../types/api'
import { LiveStateBadge } from './LiveStateBadge'
import { SourceStatusBadge } from './SourceStatusBadge'

export type RowCapability = 'history' | 'live'

interface Props {
    meteringPointId: string
    /** One row per capability the point is eligible for. */
    capabilities: RowCapability[]
    sources: SupplementarySource[] | undefined
    /** The caller may connect and change sources; a viewer only reads. */
    canManage?: boolean
    onOpenSource: (source: SupplementarySource) => void
    onConnect: (capability: RowCapability) => void
    /** Wording of an unconnected live row on a ZEV-operated meter. */
    zevHeld?: boolean
}

/**
 * What a metering point provides, one row per capability: the source that provides it as a button that
 * opens the source (a source providing both is in both rows and opens the same dialog) and how it is
 * doing, or "Not connected" with a Connect for that capability.
 */
export function CapabilityRows({ meteringPointId, capabilities, sources, canManage = true, onOpenSource, onConnect, zevHeld = false }: Props) {
    const { t } = useTranslation()
    const { isImpersonating } = useAuth()
    const { settings } = useAppSettings()
    const dateTime = (value: string | null) => (value ? formatDateTime(value, settings) : t('supplementary.never'))

    return (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: '0.6rem' }}>
            {capabilities.map((capability) => {
                const source = sourceFor(sources, meteringPointId, capability)
                return (
                    <li
                        key={capability}
                        data-capability={capability}
                        style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem 1rem', alignItems: 'center' }}
                    >
                        <strong style={{ flex: '0 0 8rem' }}>{t(`supplementary.capability.${capability}`)}</strong>
                        <div className="actions-row actions-row-wrap" style={{ minWidth: 0, flex: '1 1 14rem' }}>
                            {source ? (
                                <>
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        style={{ maxWidth: '100%', overflowWrap: 'anywhere' }}
                                        onClick={() => onOpenSource(source)}
                                    >
                                        {t(`supplementary.provider.${source.provider}`)}
                                        {source.label ? ` · ${source.label}` : ''}
                                    </button>
                                    {capability === 'history' ? (
                                        <>
                                            <SourceStatusBadge status={source.enabled ? source.status : 'disabled'} />
                                            <small className="muted">
                                                {source.synced_through
                                                    ? t('supplementary.card.syncedThrough', { date: formatDateTime(source.synced_through, settings) })
                                                    : t('supplementary.card.noData')}
                                            </small>
                                        </>
                                    ) : (
                                        <>
                                            {source.live_state ? <LiveStateBadge state={source.live_state} /> : null}
                                            <small className="muted">{t('supplementary.card.lastValueAt', { date: dateTime(source.live_last_seen_at) })}</small>
                                        </>
                                    )}
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
                        {!source && zevHeld && capability === 'live' && <small className="muted" style={{ flexBasis: '100%' }}>{t('supplementary.live.zevNotConnected')}</small>}
                    </li>
                )
            })}
        </ul>
    )
}
