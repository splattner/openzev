import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { createApiKey, fetchApiKeys, revokeApiKey } from '../../lib/api/auth'
import { queryKeys } from '../../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../../lib/appSettings'
import { useToast } from '../../lib/toast'
import { copyToClipboard } from '../../lib/clipboard'
import type { ApiKeyWithSecret } from '../../types/api'
import { apiKeyStatus, expiryFromDays } from './apiKeyStatus'

const EXPIRY_CHOICES: Array<{ days: number | null; labelKey: string }> = [
    { days: 30, labelKey: 'account.apiKeys.expiry30' },
    { days: 90, labelKey: 'account.apiKeys.expiry90' },
    { days: 365, labelKey: 'account.apiKeys.expiry365' },
    { days: null, labelKey: 'account.apiKeys.expiryNever' },
]

interface Props {
    onRevoke: (options: { name: string; onConfirm: () => void }) => void
}

export function ApiKeysSection({ onRevoke }: Props) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()

    const [isCreating, setIsCreating] = useState(false)
    const [name, setName] = useState('')
    const [readOnly, setReadOnly] = useState(false)
    const [expiryDays, setExpiryDays] = useState<number | null>(365)
    // Held in component state only, and only until the panel is dismissed. The
    // backend stores a hash, so this is the one and only chance to copy it.
    const [freshSecret, setFreshSecret] = useState<ApiKeyWithSecret | null>(null)
    const [copied, setCopied] = useState(false)

    const keysQuery = useQuery({ queryKey: queryKeys.auth.apiKeys(), queryFn: fetchApiKeys })

    const createMutation = useMutation({
        mutationFn: () =>
            createApiKey({ name: name.trim(), read_only: readOnly, expires_at: expiryFromDays(expiryDays) }),
        onSuccess: (created) => {
            setFreshSecret(created)
            setCopied(false)
            setIsCreating(false)
            setName('')
            setReadOnly(false)
            setExpiryDays(365)
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.apiKeys() })
        },
        onError: (error: any) => {
            const data = error.response?.data
            pushToast(data?.detail ?? data?.name?.[0] ?? data?.expires_at?.[0] ?? t('common.error'), 'error')
        },
    })

    const revokeMutation = useMutation({
        mutationFn: (id: string) => revokeApiKey(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.apiKeys() })
            pushToast(t('account.apiKeys.revokeSuccess'), 'success')
        },
        onError: () => pushToast(t('common.error'), 'error'),
    })

    async function handleCopy(secret: string) {
        const ok = await copyToClipboard(secret)
        if (ok) setCopied(true)
        else pushToast(t('account.apiKeys.copyFailed'), 'error')
    }

    const keys = keysQuery.data ?? []

    return (
        <div className="card">
            <h2>{t('account.apiKeys.section')}</h2>
            <p className="muted" style={{ marginBottom: '1.5rem' }}>{t('account.apiKeys.description')}</p>

            {freshSecret && (
                <div className="warning-banner" role="alert">
                    <strong>{t('account.apiKeys.secretShownOnceTitle')}</strong>
                    <p style={{ marginTop: '0.5rem' }}>
                        {t('account.apiKeys.secretShownOnceBody')}
                    </p>
                    <code
                        data-testid="api-key-secret"
                        style={{
                            display: 'block',
                            wordBreak: 'break-all',
                            background: 'var(--surface-card)',
                            padding: '0.75rem',
                            borderRadius: '4px',
                            border: '1px solid var(--warning-200)',
                        }}
                    >
                        {freshSecret.key}
                    </code>
                    <div className="actions-row" style={{ marginTop: '0.75rem' }}>
                        <button
                            type="button"
                            className="button button-primary button-compact"
                            onClick={() => void handleCopy(freshSecret.key)}
                        >
                            {copied ? t('account.apiKeys.copied') : t('account.apiKeys.copy')}
                        </button>
                        <button
                            type="button"
                            className="button button-secondary button-compact"
                            onClick={() => setFreshSecret(null)}
                        >
                            {t('account.apiKeys.dismissSecret')}
                        </button>
                    </div>
                </div>
            )}

            {isCreating ? (
                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (!name.trim()) {
                            pushToast(t('account.apiKeys.nameRequired'), 'error')
                            return
                        }
                        createMutation.mutate()
                    }}
                    style={{ marginBottom: '1.5rem' }}
                >
                    <label>
                        <span>{t('account.apiKeys.nameLabel')}</span>
                        <input
                            type="text"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            placeholder={t('account.apiKeys.namePlaceholder')}
                        />
                    </label>

                    <label>
                        <span>{t('account.apiKeys.expiryLabel')}</span>
                        <select
                            value={expiryDays === null ? 'never' : String(expiryDays)}
                            onChange={(event) =>
                                setExpiryDays(event.target.value === 'never' ? null : Number(event.target.value))
                            }
                        >
                            {EXPIRY_CHOICES.map((choice) => (
                                <option
                                    key={choice.labelKey}
                                    value={choice.days === null ? 'never' : String(choice.days)}
                                >
                                    {t(choice.labelKey)}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <input
                            type="checkbox"
                            checked={readOnly}
                            onChange={(event) => setReadOnly(event.target.checked)}
                        />
                        <span>{t('account.apiKeys.readOnlyLabel')}</span>
                    </label>
                    <small className="muted" style={{ marginTop: '0.25rem', display: 'block' }}>
                        {t('account.apiKeys.readOnlyHint')}
                    </small>

                    <div className="actions-row">
                        <button type="submit" className="button button-primary" disabled={createMutation.isPending}>
                            {createMutation.isPending ? t('common.saving') : t('account.apiKeys.create')}
                        </button>
                        <button
                            type="button"
                            className="button button-secondary"
                            onClick={() => setIsCreating(false)}
                        >
                            {t('common.cancel')}
                        </button>
                    </div>
                </form>
            ) : (
                <button
                    type="button"
                    className="button button-primary"
                    style={{ marginBottom: '1.5rem' }}
                    onClick={() => setIsCreating(true)}
                >
                    {t('account.apiKeys.newKey')}
                </button>
            )}

            {keysQuery.isLoading && <p className="muted">{t('common.loading')}</p>}

            {!keysQuery.isLoading && keys.length === 0 && (
                <p className="muted">{t('account.apiKeys.empty')}</p>
            )}

            {keys.map((key) => {
                const status = apiKeyStatus(key)
                return (
                    <div
                        key={key.id}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '1rem',
                            padding: '0.75rem 0',
                            borderBottom: '1px solid var(--border)',
                        }}
                    >
                        <div style={{ minWidth: 0 }}>
                            <strong>{key.name}</strong>
                            {key.read_only && (
                                <span className="badge" style={{ marginLeft: '0.5rem' }}>
                                    {t('account.apiKeys.readOnlyBadge')}
                                </span>
                            )}
                            {status !== 'active' && (
                                <span
                                    className="badge"
                                    style={{ marginLeft: '0.5rem', background: 'var(--warning-100)', color: 'var(--warning-800)' }}
                                >
                                    {t(
                                        status === 'expired'
                                            ? 'account.apiKeys.expiredBadge'
                                            : 'account.apiKeys.expiringBadge',
                                    )}
                                </span>
                            )}
                            <small className="muted" style={{ display: 'block' }}>
                                <code>{key.prefix}</code>
                                {' · '}
                                {t('account.apiKeys.createdOn', { date: formatDateTime(key.created_at, settings) })}
                                {' · '}
                                {key.last_used_at
                                    ? t('account.apiKeys.lastUsed', {
                                          date: formatDateTime(key.last_used_at, settings),
                                      })
                                    : t('account.apiKeys.neverUsed')}
                                {' · '}
                                {key.expires_at
                                    ? t('account.apiKeys.expiresOn', {
                                          date: formatDateTime(key.expires_at, settings),
                                      })
                                    : t('account.apiKeys.noExpiry')}
                            </small>
                        </div>
                        <button
                            type="button"
                            className="button button-danger button-compact"
                            disabled={revokeMutation.isPending}
                            onClick={() =>
                                onRevoke({ name: key.name, onConfirm: () => revokeMutation.mutate(key.id) })
                            }
                        >
                            {t('account.apiKeys.revoke')}
                        </button>
                    </div>
                )
            })}
        </div>
    )
}
