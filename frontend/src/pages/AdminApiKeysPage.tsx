import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { fetchAllApiKeys, fetchUsers, revokeAnyApiKey } from '../lib/api/auth'
import { formatApiError } from '../lib/api/errors'
import { queryKeys } from '../lib/api/queryKeys'
import { formatDateTime, useAppSettings } from '../lib/appSettings'
import { useToast } from '../lib/toast'
import { ConfirmDialog, useConfirmDialog } from '../components/ConfirmDialog'
import { StatCard } from '../components/StatCard'
import { apiKeyStatus } from '../features/account/apiKeyStatus'
import type { AdminApiKey } from '../types/api'

type StatusFilter = '' | 'active' | 'revoked'

export function AdminApiKeysPage() {
    const { t } = useTranslation()
    const { settings } = useAppSettings()
    const { pushToast } = useToast()
    const queryClient = useQueryClient()
    const { dialog, confirm, handleConfirm, handleCancel, isLoading: dialogLoading } = useConfirmDialog()

    const [userFilter, setUserFilter] = useState<number | ''>('')
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('')

    const keysQuery = useQuery({
        queryKey: queryKeys.auth.allApiKeys(userFilter, statusFilter),
        queryFn: () => fetchAllApiKeys({ user: userFilter, status: statusFilter }),
    })

    const usersQuery = useQuery({
        queryKey: queryKeys.auth.users(),
        queryFn: fetchUsers,
    })

    const keys = keysQuery.data ?? []
    const users = usersQuery.data?.results ?? []

    const revokeMutation = useMutation({
        mutationFn: (id: string) => revokeAnyApiKey(id),
        onSuccess: () => {
            void queryClient.invalidateQueries({ queryKey: ['auth', 'all-api-keys'] })
            pushToast(t('pages.adminApiKeys.revokeSuccess'), 'success')
        },
        onError: (error) => pushToast(formatApiError(error, t('common.error')), 'error'),
    })

    const activeCount = keys.filter((key) => !key.is_revoked && !key.is_expired).length
    const revokedCount = keys.filter((key) => key.is_revoked).length
    const expiringCount = keys.filter(
        (key) => !key.is_revoked && apiKeyStatus(key) === 'expiring',
    ).length

    function handleRevoke(key: AdminApiKey) {
        confirm({
            title: t('pages.adminApiKeys.revokeConfirmTitle'),
            message: t('pages.adminApiKeys.revokeConfirmMessage', {
                name: key.name,
                user: key.user_email || key.username,
            }),
            confirmText: t('pages.adminApiKeys.revoke'),
            isDangerous: true,
            onConfirm: () => revokeMutation.mutate(key.id),
        })
    }

    function statusLabel(key: AdminApiKey): { label: string; className: string } {
        if (key.is_revoked) return { label: t('pages.adminApiKeys.statusRevoked'), className: 'badge badge-danger' }
        if (key.is_expired) return { label: t('pages.adminApiKeys.statusExpired'), className: 'badge badge-warning' }
        if (apiKeyStatus(key) === 'expiring') {
            return { label: t('pages.adminApiKeys.statusExpiring'), className: 'badge badge-warning' }
        }
        return { label: t('pages.adminApiKeys.statusActive'), className: 'badge badge-success' }
    }

    return (
        <div className="page-stack">
            <header>
                <h2>{t('pages.adminApiKeys.title')}</h2>
                <p className="muted">{t('pages.adminApiKeys.description')}</p>
            </header>

            {/* Matches the inline grid the other stat rows use; there is no
                shared `.stat-grid` class in the stylesheet. */}
            <div
                style={{
                    display: 'grid',
                    gap: '1rem',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                }}
            >
                <StatCard label={t('pages.adminApiKeys.statActive')} value={activeCount} />
                <StatCard label={t('pages.adminApiKeys.statExpiring')} value={expiringCount} />
                <StatCard label={t('pages.adminApiKeys.statRevoked')} value={revokedCount} />
            </div>

            <section className="card">
                <div className="form-grid" style={{ gap: '1rem' }}>
                    <div className="form-group">
                        <label htmlFor="api-key-user-filter">{t('pages.adminApiKeys.filterUser')}</label>
                        <select
                            id="api-key-user-filter"
                            value={userFilter === '' ? '' : String(userFilter)}
                            onChange={(event) =>
                                setUserFilter(event.target.value === '' ? '' : Number(event.target.value))
                            }
                        >
                            <option value="">{t('pages.adminApiKeys.filterAllUsers')}</option>
                            {users.map((user) => (
                                <option key={user.id} value={user.id}>
                                    {user.email || user.username}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="form-group">
                        <label htmlFor="api-key-status-filter">{t('pages.adminApiKeys.filterStatus')}</label>
                        <select
                            id="api-key-status-filter"
                            value={statusFilter}
                            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                        >
                            <option value="">{t('pages.adminApiKeys.filterAllStatuses')}</option>
                            <option value="active">{t('pages.adminApiKeys.statusActive')}</option>
                            <option value="revoked">{t('pages.adminApiKeys.statusRevoked')}</option>
                        </select>
                    </div>
                </div>
            </section>

            {keysQuery.isLoading ? (
                <div className="card">{t('common.loading')}</div>
            ) : keysQuery.isError ? (
                <div className="card error-banner">{t('common.error')}</div>
            ) : keys.length === 0 ? (
                <div className="card muted">{t('pages.adminApiKeys.empty')}</div>
            ) : (
                <section className="card table-scroll">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('pages.adminApiKeys.colName')}</th>
                                <th>{t('pages.adminApiKeys.colOwner')}</th>
                                <th>{t('pages.adminApiKeys.colPrefix')}</th>
                                <th>{t('pages.adminApiKeys.colScope')}</th>
                                <th>{t('pages.adminApiKeys.colStatus')}</th>
                                <th>{t('pages.adminApiKeys.colLastUsed')}</th>
                                <th>{t('pages.adminApiKeys.colExpires')}</th>
                                <th />
                            </tr>
                        </thead>
                        <tbody>
                            {keys.map((key) => {
                                const status = statusLabel(key)
                                return (
                                    <tr key={key.id}>
                                        <td>{key.name}</td>
                                        <td>
                                            {key.user_email || key.username}
                                            <small className="muted" style={{ display: 'block' }}>{key.user_role}</small>
                                        </td>
                                        <td><code>{key.prefix}</code></td>
                                        <td>
                                            {key.read_only
                                                ? t('pages.adminApiKeys.scopeReadOnly')
                                                : t('pages.adminApiKeys.scopeFull')}
                                        </td>
                                        <td><span className={status.className}>{status.label}</span></td>
                                        <td>
                                            {key.last_used_at
                                                ? formatDateTime(key.last_used_at, settings)
                                                : t('pages.adminApiKeys.neverUsed')}
                                        </td>
                                        <td>
                                            {key.expires_at
                                                ? formatDateTime(key.expires_at, settings)
                                                : t('pages.adminApiKeys.noExpiry')}
                                        </td>
                                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                                            {!key.is_revoked && (
                                                <button
                                                    type="button"
                                                    className="button button-sm button-danger"
                                                    disabled={revokeMutation.isPending}
                                                    onClick={() => handleRevoke(key)}
                                                >
                                                    {t('pages.adminApiKeys.revoke')}
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
                {t('pages.adminApiKeys.createNote')}
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
