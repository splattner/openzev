import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { CopyButton } from '../../components/CopyButton'
import { SecretReveal } from '../../components/SecretReveal'
import { CSV_COLUMNS, ingestUrl, LIVE_EXAMPLE_PAYLOAD, liveIngestUrl } from '../../lib/supplementary'

/** What the token's source provides; a history source is the default. */
export interface PushCapabilities {
    history: boolean
    live: boolean
}

interface Props {
    token: string
    /** Clears the token on a page; a dialog leaves it out and closes with its own Done. */
    onDismiss?: () => void
    capabilities?: PushCapabilities
}

/** A push token is stored as a hash: this is the one and only time it can be read. */
export function PushTokenPanel({ token, onDismiss, capabilities = { history: true, live: false } }: Props) {
    const { t } = useTranslation()

    return (
        <SecretReveal
            secret={token}
            testId="push-token"
            title={t('supplementary.push.shownOnceTitle')}
            body={t('supplementary.push.shownOnceBody')}
            onDismiss={onDismiss}
        >
            <PushEndpoints capabilities={capabilities} />
        </SecretReveal>
    )
}

/** Where a push source's data goes: the history endpoint and CSV columns, the live endpoint and its sample, or both. */
export function PushEndpoints({ capabilities }: { capabilities: PushCapabilities }) {
    const { t } = useTranslation()
    const historyLabel = useId()
    const liveLabel = useId()
    const historyUrl = ingestUrl()
    const liveUrl = liveIngestUrl()
    return (
        <>
            {capabilities.history && (
                <>
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong id={historyLabel}>{t('supplementary.push.endpoint')}</strong>
                        <div className="copy-row">
                            <code>POST {historyUrl}</code>
                            <CopyButton value={historyUrl} labelId={historyLabel} />
                        </div>
                        <small className="muted">{t('supplementary.push.endpointHint')}</small>
                    </div>
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong>{t('supplementary.push.columns')}</strong>
                        <code style={{ wordBreak: 'break-all' }}>{CSV_COLUMNS.join(',')}</code>
                        <small className="muted">{t('supplementary.push.columnsHint')}</small>
                    </div>
                </>
            )}
            {capabilities.live && (
                <>
                    <div style={{ display: 'grid', gap: '0.35rem' }} data-testid="live-endpoint">
                        <strong id={liveLabel}>{t('supplementary.push.liveEndpoint')}</strong>
                        <div className="copy-row">
                            <code>POST {liveUrl}</code>
                            <CopyButton value={liveUrl} labelId={liveLabel} />
                        </div>
                        <small className="muted">{t('supplementary.push.liveEndpointHint')}</small>
                    </div>
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong>{t('supplementary.push.liveExample')}</strong>
                        <code style={{ wordBreak: 'break-all' }}>{LIVE_EXAMPLE_PAYLOAD}</code>
                        <small className="muted">{t('supplementary.push.liveSignHint')}</small>
                    </div>
                </>
            )}
        </>
    )
}
