import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { SecretReveal } from '../../components/SecretReveal'

export type AccountCreatedNoticeData = {
    username: string
    /** Present only when the server generated one — not when the caller supplied their own. */
    password?: string
}

/**
 * Shows a freshly created account's generated password, once. The console
 * never asks an admin to choose a password for someone else, so this is the
 * only moment it exists outside the database's hash of it.
 */
export function AccountCreatedNotice({ notice, onDismiss }: { notice: AccountCreatedNoticeData; onDismiss: () => void }) {
    const { t } = useTranslation()

    if (notice.password) {
        return (
            <section className="card">
                <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.accounts.createModal.createdTitle')}</h3>
                <SecretReveal
                    secret={notice.password}
                    testId="account-created-password"
                    title={t('pages.accounts.createModal.passwordLabel')}
                    body={t('pages.accounts.createModal.createdMessage', { username: notice.username })}
                    onDismiss={onDismiss}
                />
            </section>
        )
    }

    return (
        <section className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.accounts.createModal.createdTitle')}</h3>
                    <p className="muted mt-0">{t('pages.accounts.createModal.createdMessageOwnPassword', { username: notice.username })}</p>
                </div>
                <div className="actions-row actions-row-wrap actions-row-end">
                    <button className="button button-secondary button-compact" type="button" onClick={onDismiss}>
                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                        {t('pages.accounts.createModal.dismiss')}
                    </button>
                </div>
            </div>
        </section>
    )
}
