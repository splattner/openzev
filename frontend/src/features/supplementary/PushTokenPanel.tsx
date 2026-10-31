import { useTranslation } from 'react-i18next'
import { SecretReveal } from '../../components/SecretReveal'
import { copyToClipboard } from '../../lib/clipboard'
import { CSV_COLUMNS, ingestUrl, LIVE_EXAMPLE_PAYLOAD, liveIngestUrl } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'

/** What the token's source provides; a history source is the default. */
export interface PushCapabilities {
    history: boolean
    live: boolean
}

interface Props {
    token: string
    onDismiss: () => void
    capabilities?: PushCapabilities
}

/**
 * A push token is stored as a hash: this is the one and only time it can be read.
 * Held in component state by the caller and dropped on dismiss.
 */
export function PushTokenPanel({ token, onDismiss, capabilities = { history: true, live: false } }: Props) {
    const { t } = useTranslation()

    return (
        <SecretReveal
            secret={token}
            onDismiss={onDismiss}
            testId="push-token"
            title={t('supplementary.push.shownOnceTitle')}
            body={t('supplementary.push.shownOnceBody')}
            labels={{
                copy: t('supplementary.push.copy'),
                copied: t('supplementary.push.copied'),
                dismiss: t('supplementary.push.dismiss'),
                copyFailed: t('supplementary.push.copyFailed'),
            }}
        >
            <PushEndpoints capabilities={capabilities} />
        </SecretReveal>
    )
}

/** Where a push source's data goes: the history endpoint and CSV columns, the live endpoint and its sample, or both. */
export function PushEndpoints({ capabilities }: { capabilities: PushCapabilities }) {
    const { t } = useTranslation()
    const { pushToast } = useToast()

    async function copyUrl(url: string) {
        if (!(await copyToClipboard(url))) pushToast(t('supplementary.push.copyFailed'), 'error')
    }

    const historyUrl = ingestUrl()
    const liveUrl = liveIngestUrl()
    return (
        <>
            {capabilities.history && (
                <>
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong>{t('supplementary.push.endpoint')}</strong>
                        <code style={{ wordBreak: 'break-all' }}>POST {historyUrl}</code>
                        <small className="muted">{t('supplementary.push.endpointHint')}</small>
                        <button type="button" className="button button-secondary button-compact" onClick={() => void copyUrl(historyUrl)}>
                            {t('supplementary.push.copyUrl')}
                        </button>
                    </div>
                    <div style={{ display: 'grid', gap: '0.35rem' }}>
                        <strong>{t('supplementary.push.columns')}</strong>
                        <code>{CSV_COLUMNS.join(',')}</code>
                        <small className="muted">{t('supplementary.push.columnsHint')}</small>
                    </div>
                </>
            )}
            {capabilities.live && (
                <>
                    <div style={{ display: 'grid', gap: '0.35rem' }} data-testid="live-endpoint">
                        <strong>{t('supplementary.push.liveEndpoint')}</strong>
                        <code style={{ wordBreak: 'break-all' }}>POST {liveUrl}</code>
                        <small className="muted">{t('supplementary.push.liveEndpointHint')}</small>
                        <button type="button" className="button button-secondary button-compact" onClick={() => void copyUrl(liveUrl)}>
                            {t('supplementary.push.copyLiveUrl')}
                        </button>
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
