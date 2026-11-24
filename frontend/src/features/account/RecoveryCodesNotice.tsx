import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faDownload } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { SecretReveal } from '../../components/SecretReveal'
import { downloadBlob } from '../../lib/downloadBlob'

interface Props {
    codes: string[]
    onDismiss: () => void
}

/**
 * The one-time display of recovery codes. Shown right after a first factor is
 * enrolled or the codes are regenerated, and never again: the backend keeps
 * only hashes, and this lives in component state only.
 */
export function RecoveryCodesNotice({ codes, onDismiss }: Props) {
    const { t } = useTranslation()
    const text = codes.join('\n')

    return (
        <div className="mb-15">
            <SecretReveal
                secret={text}
                testId="recovery-codes"
                title={t('account.mfa.recoveryCodesShownOnceTitle')}
                body={t('account.mfa.recoveryCodesShownOnceBody')}
                onDismiss={onDismiss}
                actions={
                    <button
                        type="button"
                        className="button button-secondary button-compact"
                        onClick={() => downloadBlob(new Blob([text + '\n'], { type: 'text/plain' }), 'openzev-recovery-codes.txt')}
                    >
                        <FontAwesomeIcon icon={faDownload} fixedWidth />
                        {t('account.mfa.download')}
                    </button>
                }
            />
        </div>
    )
}
