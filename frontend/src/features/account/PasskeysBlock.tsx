import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { passkeyRegisterBegin, passkeyRegisterComplete, removePasskey, renamePasskey } from '../../lib/api/auth'
import { formatApiError } from '../../lib/api/errors'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import { createPasskey, isPasskeySupported, PasskeyCancelledError } from '../../lib/webauthn'
import type { Passkey } from '../../types/api'

interface Props {
    passkeys: Passkey[]
    /** Called with the recovery codes when this passkey was the first factor. */
    onRecoveryCodes: (codes: string[]) => void
    onRemove: (passkey: Passkey, onConfirm: () => void) => void
}

/**
 * Passkeys: list, rename, remove, add. A user-verified passkey signs in on
 * its own — no password (ADR 0020) — so this is where a user opts in to that.
 * Spec 2026-09-two-factor-authentication.md §7.2.
 */
export function PasskeysBlock({ passkeys, onRecoveryCodes, onRemove }: Props) {
    const { t } = useTranslation()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { settings } = useAppSettings()
    const supported = isPasskeySupported()

    const [adding, setAdding] = useState(false)
    const [newName, setNewName] = useState('')
    const [renamingId, setRenamingId] = useState<string | null>(null)
    const [renameValue, setRenameValue] = useState('')

    function refresh() {
        void queryClient.invalidateQueries({ queryKey: queryKeys.auth.mfa() })
    }

    const addMutation = useMutation({
        mutationFn: async (name: string) => {
            const options = await passkeyRegisterBegin()
            const credential = await createPasskey(options)
            return passkeyRegisterComplete(credential, name)
        },
        onSuccess: ({ recovery_codes }) => {
            setAdding(false)
            setNewName('')
            refresh()
            if (recovery_codes.length > 0) onRecoveryCodes(recovery_codes)
            pushToast(t('account.passkeys.addedSuccess'), 'success')
        },
        onError: (error) => {
            // Dismissing the browser prompt is a choice, not a failure.
            if (error instanceof PasskeyCancelledError) return
            pushToast(formatApiError(error, t('account.passkeys.addFailed')), 'error')
        },
    })

    const renameMutation = useMutation({
        mutationFn: ({ id, name }: { id: string; name: string }) => renamePasskey(id, name),
        onSuccess: () => {
            setRenamingId(null)
            refresh()
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const removeMutation = useMutation({
        mutationFn: removePasskey,
        onSuccess: () => {
            refresh()
            pushToast(t('account.passkeys.removedSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    function handleAdd(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        addMutation.mutate(newName.trim() || t('account.passkeys.defaultName'))
    }

    return (
        <div style={{ marginBottom: '1.5rem' }}>
            <strong>{t('account.passkeys.title')}</strong>
            <p className="muted">{t('account.passkeys.description')}</p>

            {passkeys.length > 0 && (
                <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 1rem' }}>
                    {passkeys.map((passkey) => (
                        <li
                            key={passkey.id}
                            style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap', padding: '0.5rem 0' }}
                        >
                            {renamingId === passkey.id ? (
                                <form
                                    style={{ display: 'flex', gap: '0.5rem', flex: '1 1 14rem' }}
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        renameMutation.mutate({ id: passkey.id, name: renameValue.trim() || passkey.name })
                                    }}
                                >
                                    <input
                                        type="text"
                                        aria-label={t('account.passkeys.nameLabel')}
                                        maxLength={100}
                                        autoFocus
                                        value={renameValue}
                                        onChange={(event) => setRenameValue(event.target.value)}
                                    />
                                    <button type="submit" className="button button-primary button-compact" disabled={renameMutation.isPending}>
                                        {t('common.save')}
                                    </button>
                                    <button type="button" className="button button-secondary button-compact" onClick={() => setRenamingId(null)}>
                                        {t('common.cancel')}
                                    </button>
                                </form>
                            ) : (
                                <>
                                    <div style={{ flex: '1 1 14rem' }}>
                                        <strong>{passkey.name || t('account.passkeys.defaultName')}</strong>
                                        <div className="muted">
                                            {t('account.passkeys.createdOn', { date: formatDateTime(passkey.created_at, settings) })}
                                            {' · '}
                                            {passkey.last_used_at
                                                ? t('account.passkeys.lastUsed', { date: formatDateTime(passkey.last_used_at, settings) })
                                                : t('account.passkeys.neverUsed')}
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        className="button button-secondary button-compact"
                                        onClick={() => {
                                            setRenamingId(passkey.id)
                                            setRenameValue(passkey.name)
                                        }}
                                    >
                                        {t('account.passkeys.rename')}
                                    </button>
                                    <button
                                        type="button"
                                        className="button button-danger button-compact"
                                        disabled={removeMutation.isPending}
                                        onClick={() => onRemove(passkey, () => removeMutation.mutate(passkey.id))}
                                    >
                                        {t('account.mfa.remove')}
                                    </button>
                                </>
                            )}
                        </li>
                    ))}
                </ul>
            )}

            {!supported ? (
                <p className="muted">{t('account.passkeys.unsupported')}</p>
            ) : adding ? (
                <form onSubmit={handleAdd}>
                    <label>
                        <span>{t('account.passkeys.nameLabel')}</span>
                        <input
                            type="text"
                            maxLength={100}
                            autoFocus
                            placeholder={t('account.passkeys.namePlaceholder')}
                            value={newName}
                            onChange={(event) => setNewName(event.target.value)}
                        />
                    </label>
                    <div className="actions-row">
                        <button type="submit" className="button button-primary" disabled={addMutation.isPending}>
                            {addMutation.isPending ? t('common.loading') : t('account.passkeys.continue')}
                        </button>
                        <button type="button" className="button button-secondary" onClick={() => setAdding(false)}>
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            ) : (
                <button type="button" className="button button-primary" onClick={() => setAdding(true)}>
                    {t('account.passkeys.add')}
                </button>
            )}
        </div>
    )
}
