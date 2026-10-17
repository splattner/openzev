import { useTranslation } from 'react-i18next'
import { SecretReveal } from '../../components/SecretReveal'
import { copyToClipboard } from '../../lib/clipboard'
import { CSV_COLUMNS, ingestUrl } from '../../lib/supplementary'
import { useToast } from '../../lib/toast'

interface Props {
    token: string
    onDismiss: () => void
}

/**
 * A push token is stored as a hash: this is the one and only time it can be read.
 * Held in component state by the caller and dropped on dismiss.
 */
export function PushTokenPanel({ token, onDismiss }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const url = ingestUrl()

    async function copyUrl() {
        if (!(await copyToClipboard(url))) pushToast(t('supplementary.push.copyFailed'), 'error')
    }

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
            <div style={{ display: 'grid', gap: '0.35rem' }}>
                <strong>{t('supplementary.push.endpoint')}</strong>
                <code style={{ wordBreak: 'break-all' }}>POST {url}</code>
                <small className="muted">{t('supplementary.push.endpointHint')}</small>
                <button type="button" className="button button-secondary button-compact" onClick={() => void copyUrl()}>
                    {t('supplementary.push.copyUrl')}
                </button>
            </div>
            <div style={{ display: 'grid', gap: '0.35rem' }}>
                <strong>{t('supplementary.push.columns')}</strong>
                <code>{CSV_COLUMNS.join(',')}</code>
                <small className="muted">{t('supplementary.push.columnsHint')}</small>
            </div>
        </SecretReveal>
    )
}
