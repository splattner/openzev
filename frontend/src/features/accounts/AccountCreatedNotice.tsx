import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faCopy, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useTranslation } from 'react-i18next'
import { copyToClipboard } from '../../lib/clipboard'
import { useToast } from '../../lib/toast'

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
    const { pushToast } = useToast()

    async function copyPassword() {
        if (!notice.password) return
        const ok = await copyToClipboard(notice.password)
        pushToast(ok ? t('pages.accounts.createModal.copied') : t('pages.accounts.createModal.copyFailed'), ok ? 'success' : 'error')
    }

    return (
        <section className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div>
                    <h3 style={{ marginTop: 0, marginBottom: '0.5rem' }}>{t('pages.accounts.createModal.createdTitle')}</h3>
                    {notice.password ? (
                        <>
                            <p className="muted" style={{ marginTop: 0 }}>{t('pages.accounts.createModal.createdMessage', { username: notice.username })}</p>
                            <p style={{ margin: '0.2rem 0', fontFamily: 'monospace', wordBreak: 'break-all' }}>{notice.password}</p>
                        </>
                    ) : (
                        <p className="muted" style={{ marginTop: 0 }}>{t('pages.accounts.createModal.createdMessageOwnPassword', { username: notice.username })}</p>
                    )}
                </div>
                <div className="actions-row actions-row-wrap actions-row-end">
                    {notice.password && (
                        <button className="button button-secondary button-compact" type="button" onClick={() => void copyPassword()}>
                            <FontAwesomeIcon icon={faCopy} fixedWidth />
                            {t('pages.accounts.createModal.copyPassword')}
                        </button>
                    )}
                    <button className="button button-secondary button-compact" type="button" onClick={onDismiss}>
                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                        {t('pages.accounts.createModal.dismiss')}
                    </button>
                </div>
            </div>
        </section>
    )
}
