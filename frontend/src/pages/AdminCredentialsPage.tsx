import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PageSkeleton } from '../components/PageSkeleton'
import { useTranslation } from 'react-i18next'
import { fetchUsers } from '../lib/api/auth'
import { fetchAllCredentials, revokeCredential } from '../lib/api/credentials'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useToast } from '../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { StatCard } from '../components/StatCard'
import { apiKeyStatus } from '../features/account/apiKeyStatus'
import type { AdminAccessCredential, CredentialKind } from '../types/api'
import { PageHeader } from '../components/PageHeader'
import { Notice } from '../components/Notice'

type StatusFilter = '' | 'active' | 'expired' | 'revoked'
type KindFilter = '' | CredentialKind

/**
 * Tokens & keys across every account (SPEC-2026-tokens-and-keys §7.4): API keys,
 * analytics tokens and energy data push tokens, with owner, type and scope.
 * Read and revoke only — an admin never mints a credential in somebody else's
 * name. `embedded` drops the page header (mounted inside the Accounts hub;
 * /admin/api-keys stays as a deep-link alias).
 */
export function AdminCredentialsPage({ embedded = false }: { embedded?: boolean }) {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [userFilter, setUserFilter] = useState<number | ''>('')
    const [kindFilter, setKindFilter] = useState<KindFilter>('')
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('')

    const credentialsQuery = useQuery({
        queryKey: queryKeys.auth.allCredentials(userFilter, kindFilter, statusFilter),
        queryFn: () => fetchAllCredentials({ user: userFilter, kind: kindFilter, status: statusFilter }),
    })
    const usersQuery = useQuery({ queryKey: queryKeys.auth.users(), queryFn: fetchUsers })

    const credentials = credentialsQuery.data ?? []
    const users = usersQuery.data ?? []

    const revokeMutation = useMutation({
        mutationFn: (credential: AdminAccessCredential) => revokeCredential(credential, { asAdmin: true }),
        onSuccess: () => {
            // Prefix-match refreshes every filter variant.
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.allCredentialsRoot })
            void queryClient.invalidateQueries({ queryKey: queryKeys.auth.credentials() })
            pushToast(t('pages.adminCredentials.revokeSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const activeCount = credentials.filter((c) => c.status === 'active').length
    const revokedCount = credentials.filter((c) => c.status === 'revoked').length
    const expiringCount = credentials.filter((c) => c.status === 'active' && apiKeyStatus(c) === 'expiring').length

    function handleRevoke(credential: AdminAccessCredential) {
        confirm({
            title: t('pages.adminCredentials.revokeConfirmTitle'),
            message: t(`pages.adminCredentials.revokeConfirmMessage.${credential.kind}`, {
                name: credential.name,
                user: ownerText(credential),
            }),
            confirmText: t('pages.adminCredentials.revoke'),
            isDangerous: true,
            onConfirm: () => revokeMutation.mutate(credential),
        })
    }

    function statusLabel(credential: AdminAccessCredential): { label: string; className: string } {
        if (credential.status === 'revoked') return { label: t('pages.adminCredentials.statusRevoked'), className: 'badge badge-danger' }
        if (credential.status === 'expired') return { label: t('pages.adminCredentials.statusExpired'), className: 'badge badge-warning' }
        if (apiKeyStatus(credential) === 'expiring') {
            return { label: t('pages.adminCredentials.statusExpiring'), className: 'badge badge-warning' }
        }
        return { label: t('pages.adminCredentials.statusActive'), className: 'badge badge-success' }
    }

    function ownerText(credential: AdminAccessCredential): string {
        if (credential.owner) return credential.owner.email || credential.owner.username
        return t('pages.adminCredentials.ownerZev', { zev: credential.scope.zev_name ?? '' })
    }

    function scopeText(credential: AdminAccessCredential): string {
        const { scope } = credential
        const parts = [scope.zev_name, scope.participant_name, scope.meter_id].filter(Boolean)
        return parts.length ? parts.join(' · ') : '—'
    }

    return (
        <div className="page-stack">
            {!embedded && (
                <PageHeader
                    eyebrow={t('nav.platformScope')}
                    title={t('pages.adminCredentials.title')}
                    description={t('pages.adminCredentials.description')}
                />
            )}

            <div className="stat-grid">
                <StatCard label={t('pages.adminCredentials.statActive')} value={activeCount} />
                <StatCard label={t('pages.adminCredentials.statExpiring')} value={expiringCount} />
                <StatCard label={t('pages.adminCredentials.statRevoked')} value={revokedCount} />
            </div>

            <section className="card">
                <div className="form-grid" style={{ gap: '1rem' }}>
                    <label>
                        <span>{t('pages.adminCredentials.filterUser')}</span>
                        <select
                            value={userFilter === '' ? '' : String(userFilter)}
                            onChange={(event) => setUserFilter(event.target.value === '' ? '' : Number(event.target.value))}
                        >
                            <option value="">{t('pages.adminCredentials.filterAllUsers')}</option>
                            {users.map((user) => (
                                <option key={user.id} value={user.id}>{user.email || user.username}</option>
                            ))}
                        </select>
                    </label>

                    <label>
                        <span>{t('pages.adminCredentials.filterKind')}</span>
                        <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value as KindFilter)}>
                            <option value="">{t('pages.adminCredentials.filterAllKinds')}</option>
                            <option value="api_key">{t('account.tokens.kind.api_key')}</option>
                            <option value="analytics">{t('account.tokens.kind.analytics')}</option>
                            <option value="energy_push">{t('account.tokens.kind.energy_push')}</option>
                        </select>
                    </label>

                    <label>
                        <span>{t('pages.adminCredentials.filterStatus')}</span>
                        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
                            <option value="">{t('pages.adminCredentials.filterAllStatuses')}</option>
                            <option value="active">{t('pages.adminCredentials.statusActive')}</option>
                            <option value="expired">{t('pages.adminCredentials.statusExpired')}</option>
                            <option value="revoked">{t('pages.adminCredentials.statusRevoked')}</option>
                        </select>
                    </label>
                </div>
            </section>

            {credentialsQuery.isLoading ? (
                <PageSkeleton variant="table" />
            ) : credentialsQuery.isError ? (
                <Notice tone="error" onRetry={() => void credentialsQuery.refetch()} isRetrying={credentialsQuery.isFetching}>{t('common.error')}</Notice>
            ) : credentials.length === 0 ? (
                <div className="card muted">{t('pages.adminCredentials.empty')}</div>
            ) : (
                <section className="card table-scroll">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.adminCredentials.colName')}</th>
                                <th>{t('pages.adminCredentials.colType')}</th>
                                <th>{t('pages.adminCredentials.colOwner')}</th>
                                <th>{t('pages.adminCredentials.colPrefix')}</th>
                                <th>{t('pages.adminCredentials.colScope')}</th>
                                <th>{t('pages.adminCredentials.colStatus')}</th>
                                <th>{t('pages.adminCredentials.colLastUsed')}</th>
                                <th>{t('pages.adminCredentials.colExpires')}</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {credentials.map((credential) => {
                                const status = statusLabel(credential)
                                return (
                                    <tr key={`${credential.kind}:${credential.id}`}>
                                        <td>{credential.name}</td>
                                        <td style={{ whiteSpace: 'nowrap' }}>
                                            {t(`account.tokens.kind.${credential.kind}`)}
                                            <small className="muted" style={{ display: 'block' }}>
                                                {t(`account.tokens.access.${credential.access}`)}
                                            </small>
                                        </td>
                                        <td>{ownerText(credential)}</td>
                                        <td><code>{credential.prefix}</code></td>
                                        <td>{scopeText(credential)}</td>
                                        <td><span className={status.className}>{status.label}</span></td>
                                        <td>
                                            {credential.last_used_at
                                                ? formatDateTime(credential.last_used_at, settings)
                                                : t('pages.adminCredentials.neverUsed')}
                                        </td>
                                        <td>
                                            {credential.expires_at
                                                ? formatDateTime(credential.expires_at, settings)
                                                : t('pages.adminCredentials.noExpiry')}
                                        </td>
                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                            {credential.status !== 'revoked' && (
                                                <button
                                                    type="button"
                                                    className="button button-danger button-compact"
                                                    disabled={revokeMutation.isPending}
                                                    aria-label={t('account.tokens.revokeNamed', { name: credential.name })}
                                                    onClick={() => handleRevoke(credential)}
                                                >
                                                    {t('pages.adminCredentials.revoke')}
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </section>
            )}

            <p className="muted" style={{ fontSize: '0.8rem' }}>
                {t('pages.adminCredentials.createNote')}
            </p>

            {dialog && (
                <ConfirmDialog
                    {...dialog}
                    isLoading={dialogLoading}
                    onConfirm={handleConfirm}
                    onCancel={handleCancel}
                />
            )}
        </div>
    )
}
