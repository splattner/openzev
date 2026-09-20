import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'
import { faLink, faXmark } from '@fortawesome/free-solid-svg-icons'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { FormModal } from '../../components/FormModal'
import type { AdminUser } from '../../types/api'

type LinkAccountModalProps = {
    participantName: string
    accounts: AdminUser[]
    error: string | null
    pending: boolean
    onSubmit: (userId: number) => void
    onClose: () => void
}

/** Pick an existing participant or guest account to attach to a participant. */
export function LinkAccountModal({ participantName, accounts, error, pending, onSubmit, onClose }: LinkAccountModalProps) {
    const { t } = useTranslation()
    const [selected, setSelected] = useState('')
    const [validation, setValidation] = useState<string | null>(null)

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (!selected) {
            setValidation(t('pages.accounts.validation.selectAccount'))
            return
        }
        onSubmit(Number(selected))
    }

    return (
        <FormModal isOpen title={t('pages.accounts.linkModal.title')} onClose={onClose} maxWidth="560px">
            <form onSubmit={submit} style={{ display: 'grid', gap: '1rem' }}>
                <p style={{ margin: 0 }}>
                    {t('pages.accounts.linkModal.participant')} <strong>{participantName}</strong>
                </p>
                <label>
                    <span>{t('pages.accounts.linkModal.existingAccount')}</span>
                    <select value={selected} onChange={(event) => setSelected(event.target.value)} required>
                        <option value="">{t('pages.accounts.linkModal.selectAccount')}</option>
                        {accounts.map((account) => (
                            <option key={account.id} value={account.id}>
                                {account.username} ({account.email || t('pages.accounts.linkModal.noEmail')})
                            </option>
                        ))}
                    </select>
                </label>

                {(validation ?? error) && <div className="error-banner">{validation ?? error}</div>}

                <div className="actions-row actions-row-end actions-row-wrap">
                    <button className="button button-secondary" type="button" onClick={onClose}>
                        <FontAwesomeIcon icon={faXmark} fixedWidth />
                        {t('common.cancel')}
                    </button>
                    <button className="button button-primary" type="submit" disabled={pending}>
                        <FontAwesomeIcon icon={faLink} fixedWidth />
                        {t('pages.accounts.linkModal.linkButton')}
                    </button>
                </div>
            </form>
        </FormModal>
    )
}
